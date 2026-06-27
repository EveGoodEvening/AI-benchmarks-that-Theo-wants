"""Scoring/verifier engine for ai-bench, chunk C04.

This module implements the built-in deterministic verifiers and the
``score_case`` / aggregate helpers consumed by the runner (C05). It depends
only on the frozen typed contracts in :mod:`ai_bench.types` (C02); it does not
touch the loader, schemas, runner, sandbox, or failure store.

v1 built-in verifiers:

  * ``exact_match``   -- observed string equals expected string.
  * ``contains_any``  -- observed string contains at least one needle.
  * ``regex_match``   -- observed string matches a regex pattern.
  * ``set_f1``        -- token-set F1 between expected and observed sets.
  * ``state_check``   -- repo-state verifier *interface shape* only; the
    enforced implementation is plugged in by C07 via
    :func:`register_state_check_verifier`.
  * ``llm_judge``     -- LLM-judge contract requiring a pinned judge
    model/prompt/params/seed. A real judge adapter is wired by the runner
    (C05); a deterministic :class:`MockLLMJudge` is provided for tests only.

Design constraints (frozen by the plan):

  * Deterministic verifier outputs are stable and explainable: every verifier
    returns a :class:`VerifierResult` with a human-readable ``reason`` and a
    ``details`` mapping.
  * No arbitrary dotted-path custom code execution is introduced in v1. The
    verifier registry is a fixed, closed mapping of built-in names to
    functions; there is no ``importlib``/``getattr`` verifier resolution.
  * The LLM-judge path cannot run without pinned judge metadata
    (``judge_model``, ``judge_prompt``, ``judge_params``, ``judge_seed``).
  * A null ``expected`` is permitted only for preserved failure cases; the
    text verifiers raise :class:`VerifierConfigurationError` when asked to
    score a null expected value rather than silently producing a verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from ai_bench.types import (
    AggregateScore,
    CaseDefinition,
    LLMJudgeConfig,
    MetricConfig,
    RepoState,
    StateCheckSpec,
    Verdict,
    VerifierName,
)

__all__ = [
    "VerifierResult",
    "CaseVerdict",
    "VerifierError",
    "VerifierNotFoundError",
    "VerifierConfigurationError",
    "StateCheckVerifier",
    "LLMJudge",
    "MockLLMJudge",
    "VERIFIERS",
    "VERIFIER_VERSION",
    "get_verifier",
    "exact_match",
    "contains_any",
    "regex_match",
    "set_f1",
    "state_check",
    "llm_judge",
    "score_case",
    "score_cases",
    "aggregate_scores",
    "register_state_check_verifier",
]

# Scorer/verifier version. Pinned into run-records via the runner (C05) so a
# changed verifier algorithm is distinguishable from a changed fixture. Bumped
# only on a deliberate algorithm change, not on fixture edits.
VERIFIER_VERSION: str = "1"

# Text verifiers that score against ``case.expected`` and reject null expected.
_TEXT_VERIFIERS: frozenset[str] = frozenset(
    {"exact_match", "contains_any", "regex_match", "set_f1"}
)


# --- Exceptions -------------------------------------------------------------


class VerifierError(Exception):
    """Base class for scoring/verifier errors."""


class VerifierNotFoundError(VerifierError):
    """Raised when an unknown verifier name is requested."""


class VerifierConfigurationError(VerifierError):
    """Raised when a verifier is misconfigured (unpinned judge, null expected,
    missing state-check spec, invalid regex, etc.).

    The runner (C05) treats this as a non-zero process failure: invalid
    verifier configuration is distinct from a case verdict of ``fail``.
    """


# --- Result types -----------------------------------------------------------


@dataclass(frozen=True)
class VerifierResult:
    """Outcome of a single verifier call.

    ``verdict`` is ``pass``/``fail``; ``score`` is in ``[0.0, 1.0]``;
    ``reason`` is a stable, human-readable explanation; ``details`` carries
    verifier-specific structured context for the run-record.
    """

    verdict: Verdict
    score: float
    reason: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseVerdict:
    """Scoring outcome for a single case, produced by :func:`score_case`.

    The runner (C05) maps this onto :class:`ai_bench.types.CaseResult` when
    writing a run-record. ``error`` is ``None`` on successful evaluation
    (including verdict ``fail``); the runner populates it when it catches a
    propagated verifier exception for a case.
    """

    case_id: str
    verdict: Verdict
    score: float
    verifier: VerifierName
    reason: str
    details: Mapping[str, Any]
    expected: Any
    observed: Any
    error: str | None = None


# A verifier function takes (expected, observed, params) and returns a
# VerifierResult, or raises a VerifierError. ``expected``/``observed`` shapes
# are verifier-specific (strings for text verifiers; StateCheckSpec/RepoState
# for state_check; any/pinned-judge for llm_judge).
VerifierFn = Callable[[Any, Any, Mapping[str, Any]], VerifierResult]


# --- Helpers ----------------------------------------------------------------


def _to_str(value: Any) -> str:
    """Coerce a scalar value to its string scoring form."""
    if value is None:
        return ""
    if isinstance(value, bool):
        # Render booleans as lowercase so True/true match case-insensitively
        # and deterministically across YAML loaders.
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return str(value)


def _collapse_whitespace(text: str) -> str:
    """Collapse runs of whitespace to single spaces (does not strip)."""
    return re.sub(r"\s+", " ", text)


def _bool_param(params: Mapping[str, Any], name: str, default: bool) -> bool:
    if name not in params:
        return default
    value = params[name]
    if isinstance(value, bool):
        return value
    raise VerifierConfigurationError(
        f"boolean verifier param {name!r} must be a bool when provided; "
        f"got {type(value).__name__}"
    )


def _to_set(
    value: Any,
    *,
    delimiter: str | None,
    case_sensitive: bool,
    role: str,
) -> frozenset[str]:
    """Build a string item-set for set_f1 from a string/list/tuple/set.

    Strings are split on ``delimiter`` (whitespace when ``None``). Items are
    coerced to strings and lowercased when ``case_sensitive`` is falsey.
    """
    if value is None:
        raise VerifierConfigurationError(
            f"set_f1 {role} is null; cannot build a scoring set"
        )
    if isinstance(value, str):
        if delimiter is None:
            items = value.split()
        elif delimiter == "":
            raise VerifierConfigurationError(
                "set_f1 delimiter must be a non-empty string or null "
                "(whitespace); an empty string is not a valid delimiter"
            )
        else:
            items = value.split(delimiter)
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        raise VerifierConfigurationError(
            f"set_f1 {role} must be a string, list, tuple, or set; "
            f"got {type(value).__name__}"
        )

    out: set[str] = set()
    for item in items:
        s = _to_str(item)
        if not case_sensitive:
            s = s.lower()
        out.add(s)
    return frozenset(out)


def _regex_flags(flags: Any) -> int:
    """Translate verifier params flags into ``re`` flag bits.

    Accepts a list/tuple/set of flag name strings, a single flag name string,
    or ``None``. Supported names: ``ignorecase``, ``multiline``, ``dotall``,
    ``verbose``. Unknown names raise :class:`VerifierConfigurationError`. This
    keeps regex configuration declarative and deterministic (no ``eval``).
    """
    if flags is None:
        return 0
    if isinstance(flags, str):
        names: Sequence[str] = (flags,)
    elif isinstance(flags, (list, tuple, set)):
        names = list(flags)
    else:
        raise VerifierConfigurationError(
            "regex_match flags must be a string or a list of flag names "
            "(ignorecase, multiline, dotall, verbose)"
        )
    table = {
        "ignorecase": re.IGNORECASE,
        "multiline": re.MULTILINE,
        "dotall": re.DOTALL,
        "verbose": re.VERBOSE,
    }
    bits = 0
    for name in names:
        key = str(name).lower()
        if key not in table:
            raise VerifierConfigurationError(
                f"regex_match unknown flag {name!r}; supported: "
                f"{sorted(table)}"
            )
        bits |= table[key]
    return bits


def _to_state_check_spec(value: Any) -> StateCheckSpec:
    """Accept a StateCheckSpec or a mapping and return a StateCheckSpec."""
    if isinstance(value, StateCheckSpec):
        return value
    if isinstance(value, Mapping):
        return StateCheckSpec(
            files=dict(value.get("files") or {}),
            git=dict(value.get("git") or {}),
            absent=tuple(value.get("absent") or ()),
        )
    raise VerifierConfigurationError(
        "state_check expected must be a StateCheckSpec or a mapping; "
        f"got {type(value).__name__}"
    )


def _to_repo_state(value: Any) -> RepoState:
    """Accept a RepoState or a mapping and return a RepoState."""
    if isinstance(value, RepoState):
        return value
    if isinstance(value, Mapping):
        missing = [
            k for k in ("file_tree", "git_status", "branches", "commits", "diff")
            if k not in value
        ]
        if missing:
            raise VerifierConfigurationError(
                f"state_check observed repo state missing fields: {missing}"
            )
        return RepoState(
            file_tree=tuple(value["file_tree"]),
            git_status=str(value["git_status"]),
            branches=tuple(value["branches"]),
            commits=tuple(value["commits"]),
            diff=str(value["diff"]),
        )
    raise VerifierConfigurationError(
        "state_check observed must be a RepoState or a mapping; "
        f"got {type(value).__name__}"
    )


def _resolve_judge_config(params: Mapping[str, Any]) -> LLMJudgeConfig:
    """Resolve and validate a pinned LLM-judge config from verifier params.

    Accepts an :class:`LLMJudgeConfig` or a mapping with the four required
    pinned fields. Raises :class:`VerifierConfigurationError` if any pinned
    field is missing or empty -- the LLM-judge path cannot run without pinned
    metadata.
    """
    cfg = params.get("judge_config")
    if cfg is None:
        raise VerifierConfigurationError(
            "llm_judge requires a pinned judge_config "
            "(judge_model, judge_prompt, judge_params, judge_seed)"
        )
    if isinstance(cfg, LLMJudgeConfig):
        _validate_pinned_judge(cfg)
        return cfg
    if isinstance(cfg, Mapping):
        if "judge_params" not in cfg:
            raise VerifierConfigurationError(
                "llm_judge judge_config.judge_params is required and must be a mapping"
            )
        judge_params = cfg["judge_params"]
        if not isinstance(judge_params, Mapping):
            raise VerifierConfigurationError(
                "llm_judge judge_config.judge_params must be a mapping"
            )
        built = LLMJudgeConfig(
            judge_model=str(cfg.get("judge_model") or ""),
            judge_prompt=str(cfg.get("judge_prompt") or ""),
            judge_seed=cfg.get("judge_seed"),
            judge_params=dict(judge_params),
        )
        _validate_pinned_judge(built)
        return built
    raise VerifierConfigurationError(
        "llm_judge judge_config must be an LLMJudgeConfig or a mapping; "
        f"got {type(cfg).__name__}"
    )


def _validate_pinned_judge(cfg: LLMJudgeConfig) -> None:
    if not cfg.judge_model:
        raise VerifierConfigurationError(
            "llm_judge judge_config.judge_model is required and non-empty"
        )
    if not cfg.judge_prompt:
        raise VerifierConfigurationError(
            "llm_judge judge_config.judge_prompt is required and non-empty"
        )
    if cfg.judge_seed is None or cfg.judge_seed == "":
        raise VerifierConfigurationError(
            "llm_judge judge_config.judge_seed is required and non-null"
        )
    if not isinstance(cfg.judge_params, Mapping):
        raise VerifierConfigurationError(
            "llm_judge judge_config.judge_params must be a mapping"
        )


# --- Built-in text verifiers ------------------------------------------------


def exact_match(
    expected: Any, observed: Any, params: Mapping[str, Any]
) -> VerifierResult:
    """Pass iff the observed string exactly equals the expected string.

    Params:
      * ``case_sensitive`` (bool, default False).
      * ``trim`` (bool, default True) -- strip surrounding whitespace.
      * ``normalize_whitespace`` (bool, default False) -- collapse internal
        whitespace runs to single spaces before comparison.
    """
    case_sensitive = _bool_param(params, "case_sensitive", False)
    trim = _bool_param(params, "trim", True)
    normalize_ws = _bool_param(params, "normalize_whitespace", False)

    exp = _to_str(expected)
    obs = _to_str(observed)
    if trim:
        exp = exp.strip()
        obs = obs.strip()
    if normalize_ws:
        exp = _collapse_whitespace(exp)
        obs = _collapse_whitespace(obs)
    if not case_sensitive:
        exp_cmp = exp.lower()
        obs_cmp = obs.lower()
    else:
        exp_cmp = exp
        obs_cmp = obs

    ok = exp_cmp == obs_cmp
    return VerifierResult(
        verdict="pass" if ok else "fail",
        score=1.0 if ok else 0.0,
        reason="exact match" if ok else "observed does not exactly match expected",
        details={
            "case_sensitive": case_sensitive,
            "trim": trim,
            "normalize_whitespace": normalize_ws,
            "expected": exp,
            "observed": obs,
        },
    )


def contains_any(
    expected: Any, observed: Any, params: Mapping[str, Any]
) -> VerifierResult:
    """Pass iff the observed string contains at least one needle.

    Needles are taken from ``params["needles"]`` when present: a scalar string
    is treated as one needle, while list/tuple/set values are collections of
    needles. Otherwise, needles come from ``expected`` using the same rules.
    Empty needles are ignored. The verifier
    fails when no non-empty needle is contained in the observed string.

    Params:
      * ``needles`` (str | list[str], optional) -- overrides ``expected``.
      * ``case_sensitive`` (bool, default False).
      * ``trim`` (bool, default True) -- strip needles and observed.
    """
    case_sensitive = _bool_param(params, "case_sensitive", False)
    trim = _bool_param(params, "trim", True)

    needles_raw = params.get("needles")
    if needles_raw is None:
        if isinstance(expected, (list, tuple, set)):
            needle_items = list(expected)
        else:
            needle_items = [expected]
    elif isinstance(needles_raw, str):
        needle_items = [needles_raw]
    elif isinstance(needles_raw, (list, tuple, set)):
        needle_items = list(needles_raw)
    else:
        raise VerifierConfigurationError(
            "contains_any needles must be a string or a list/tuple/set; "
            f"got {type(needles_raw).__name__}"
        )
    def _norm(s: str) -> str:
        s = _to_str(s)
        if trim:
            s = s.strip()
        return s if case_sensitive else s.lower()

    needles = [_norm(n) for n in needle_items]
    obs = _norm(observed)

    matched = [n for n in needles if n != "" and n in obs]
    ok = len(matched) > 0
    return VerifierResult(
        verdict="pass" if ok else "fail",
        score=1.0 if ok else 0.0,
        reason=(
            "observed contains a required needle"
            if ok
            else "observed contains none of the required needles"
        ),
        details={
            "case_sensitive": case_sensitive,
            "trim": trim,
            "needles": needles,
            "matched": matched,
            "observed": obs,
        },
    )


def regex_match(
    expected: Any, observed: Any, params: Mapping[str, Any]
) -> VerifierResult:
    """Pass iff the observed string matches a regex pattern.

    The pattern is taken from ``params["pattern"]`` when present, otherwise
    from ``expected`` (coerced to a string). By default a ``re.search`` match
    is required; set ``fullmatch`` true to require a full match.

    Params:
      * ``pattern`` (str, optional) -- overrides ``expected``.
      * ``fullmatch`` (bool, default False).
      * ``flags`` (str | list[str], optional) -- one or more of
        ``ignorecase``, ``multiline``, ``dotall``, ``verbose``.
    """
    pattern = params.get("pattern")
    if pattern is None:
        pattern = _to_str(expected)
    if not isinstance(pattern, str):
        raise VerifierConfigurationError(
            "regex_match pattern must be a string"
        )
    if pattern == "":
        raise VerifierConfigurationError(
            "regex_match pattern must be a non-empty string"
        )
    flags = _regex_flags(params.get("flags"))
    fullmatch = _bool_param(params, "fullmatch", False)
    obs = _to_str(observed)

    try:
        rx = re.compile(pattern, flags)
    except re.error as exc:
        raise VerifierConfigurationError(f"invalid regex pattern: {exc}") from exc

    m = rx.fullmatch(obs) if fullmatch else rx.search(obs)
    ok = m is not None
    return VerifierResult(
        verdict="pass" if ok else "fail",
        score=1.0 if ok else 0.0,
        reason=(
            f"regex {'fullmatch' if fullmatch else 'search'} succeeded"
            if ok
            else f"regex {'fullmatch' if fullmatch else 'search'} did not match"
        ),
        details={
            "pattern": pattern,
            "fullmatch": fullmatch,
            "flags": sorted(
                []
                if params.get("flags") is None
                else (
                    [params["flags"]]
                    if isinstance(params.get("flags"), str)
                    else list(params.get("flags") or [])
                )
            ),
            "observed": obs,
            "match_span": [m.start(), m.end()] if m is not None else None,
        },
    )


def set_f1(
    expected: Any, observed: Any, params: Mapping[str, Any]
) -> VerifierResult:
    """Token-set F1 between expected and observed sets.

    Each side is built from a string (split on ``delimiter``, whitespace when
    ``None``) or a list/tuple/set of items. Items are coerced to strings and
    lowercased when ``case_sensitive`` is falsey.

    Score is the F1 over the two sets:
    ``F1 = 2*P*R/(P+R)`` with ``P = |intersection|/|observed|`` and
    ``R = |intersection|/|expected|``. The verdict is ``pass`` when the score
    meets ``threshold`` (default ``1.0``, i.e. a perfect set match).

    Edge cases:
      * Both sets empty -> score 1.0 (a perfect match on an empty target).
      * Exactly one set empty -> score 0.0.
      * No intersection -> score 0.0.

    Params:
      * ``delimiter`` (str | None, default None) -- string split delimiter.
      * ``case_sensitive`` (bool, default False).
      * ``threshold`` (float, default 1.0) -- pass threshold in ``[0, 1]``.
    """
    delimiter = params.get("delimiter")
    if delimiter is not None and not isinstance(delimiter, str):
        raise VerifierConfigurationError(
            "set_f1 delimiter must be a string or null (whitespace)"
        )
    case_sensitive = _bool_param(params, "case_sensitive", False)
    threshold_raw = params.get("threshold", 1.0)
    try:
        threshold = float(threshold_raw)
    except (TypeError, ValueError) as exc:
        raise VerifierConfigurationError(
            "set_f1 threshold must be a number in [0, 1]"
        ) from exc
    if not 0.0 <= threshold <= 1.0:
        raise VerifierConfigurationError(
            "set_f1 threshold must be a number in [0, 1]"
        )

    exp_set = _to_set(
        expected, delimiter=delimiter, case_sensitive=case_sensitive, role="expected"
    )
    obs_set = _to_set(
        observed, delimiter=delimiter, case_sensitive=case_sensitive, role="observed"
    )

    if not exp_set and not obs_set:
        f1 = 1.0
    elif not exp_set or not obs_set:
        f1 = 0.0
    else:
        tp = len(exp_set & obs_set)
        precision = tp / len(obs_set)
        recall = tp / len(exp_set)
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    # Clamp for floating-point safety.
    f1 = max(0.0, min(1.0, f1))
    ok = f1 >= threshold
    return VerifierResult(
        verdict="pass" if ok else "fail",
        score=f1,
        reason=(
            f"set_f1={f1:.6f} >= threshold {threshold:.6f}"
            if ok
            else f"set_f1={f1:.6f} < threshold {threshold:.6f}"
        ),
        details={
            "delimiter": delimiter,
            "case_sensitive": case_sensitive,
            "threshold": threshold,
            "expected_set": sorted(exp_set),
            "observed_set": sorted(obs_set),
            "intersection": sorted(exp_set & obs_set),
            "precision": (len(exp_set & obs_set) / len(obs_set)) if obs_set else 0.0,
            "recall": (len(exp_set & obs_set) / len(exp_set)) if exp_set else 0.0,
        },
    )


# --- State-check verifier interface shape -----------------------------------


@runtime_checkable
class StateCheckVerifier(Protocol):
    """Interface shape for the repo-state verifier.

    The enforced implementation is provided by C07 (which owns the sandbox
    artifacts) and registered via :func:`register_state_check_verifier`. C04
    freezes only the interface shape so C05's replay plumbing and C08 fixtures
    can target it without depending on the sandbox.
    """

    def check(
        self,
        spec: StateCheckSpec,
        state: RepoState,
        params: Mapping[str, Any],
    ) -> VerifierResult:
        """Return a :class:`VerifierResult` for ``state`` against ``spec``."""
        ...


_state_check_impl: StateCheckVerifier | None = None


def register_state_check_verifier(impl: StateCheckVerifier) -> None:
    """Register the C07 state-check verifier implementation.

    Until an implementation is registered, :func:`state_check` raises
    :class:`NotImplementedError` so the interface shape is usable but cannot
    be accidentally satisfied by a no-op.
    """
    global _state_check_impl
    _state_check_impl = impl


def state_check(
    expected: Any, observed: Any, params: Mapping[str, Any]
) -> VerifierResult:
    """State-check verifier entry point.

    ``expected`` is a :class:`StateCheckSpec` (or mapping); ``observed`` is a
    :class:`RepoState` (or mapping). The repo-state checks are implemented by
    a :class:`RepoStateVerifier` registered via
    :func:`register_state_check_verifier`. C07.2 provides a real default
    implementation (:class:`RepoStateVerifier`) that the runner registers for
    tool-task runs; until an implementation is registered, this raises
    :class:`NotImplementedError` so the interface shape cannot be accidentally
    satisfied by a no-op (preserved from C04).
    """
    spec = _to_state_check_spec(expected)
    state = _to_repo_state(observed)
    if _state_check_impl is None:
        raise NotImplementedError(
            "state_check verifier implementation is provided by C07; "
            "register one via register_state_check_verifier() before scoring "
            "tool-task cases"
        )
    return _state_check_impl.check(spec, state, params)


class RepoStateVerifier:
    """Real repo-state verifier implementation (C07.2).

    Checks a :class:`RepoState` snapshot against a :class:`StateCheckSpec`:

    * ``spec.files``: each named file must exist (or not), optionally contain a
      substring, and/or match a pinned sha256 of its contents.
    * ``spec.git``: ``branches`` (expected branch names present), ``commits``
      (mapping of sha-prefix -> subject substring), ``status_clean`` (git
      status must be empty), and ``head_commit_message`` (HEAD subject must
      contain the substring).
    * ``spec.absent``: each named path must NOT exist in the file tree.

    The verifier is deterministic and explains every mismatch in ``reason``
    and ``details`` so failures are actionable. It operates purely on the
    snapshot fields frozen by C02; it does not touch the filesystem.
    """

    def check(
        self,
        spec: StateCheckSpec,
        state: RepoState,
        params: Mapping[str, Any],
    ) -> VerifierResult:
        del params
        mismatches: list[str] = []
        details: dict[str, Any] = {
            "files_checked": len(spec.files),
            "absent_checked": len(spec.absent),
            "git_checks": list(spec.git.keys()),
        }

        tree = set(state.file_tree)

        for path, assertion in spec.files.items():
            exists = assertion.get("exists", True) if assertion else True
            present = path in tree
            if exists and not present:
                mismatches.append(f"file {path!r} expected to exist but is absent")
                continue
            if not exists and present:
                mismatches.append(f"file {path!r} expected to be absent but exists")
                continue
            if not present:
                continue
            contains = assertion.get("contains") if assertion else None
            if contains is not None:
                # C07 review: enforce contains, never silently pass it.  The
                # snapshot carries a path-only file_tree plus a unified diff;
                # content can only be verified when the file appears in the
                # diff.  If the file is present but not in the diff, the
                # assertion is unverifiable from the snapshot and MUST fail
                # closed rather than pass unchecked.
                if contains:
                    if _diff_has_file(state.diff, path):
                        if not _diff_file_contains(state.diff, path, contains):
                            mismatches.append(
                                f"file {path!r} expected to contain "
                                f"{contains!r} but the snapshot diff does not"
                            )
                    else:
                        mismatches.append(
                            f"file {path!r} expected to contain {contains!r} "
                            "but its content is not available in the snapshot "
                            "diff; the assertion cannot be verified and fails "
                            "closed"
                        )
            sha = assertion.get("sha256") if assertion else None
            if sha is not None:
                # C07 review: sha256 content assertions cannot be verified
                # from a path-only file_tree + unified diff (the C02 RepoState
                # does not carry content hashes).  Rather than silently passing
                # an unchecked assertion, fail closed so fixtures cannot claim
                # a content hash that was never actually checked.
                mismatches.append(
                    f"file {path!r} sha256 assertion cannot be verified from "
                    "the repo-state snapshot (no content hashes available); "
                    "use a contains/diff assertion instead"
                )

        for path in spec.absent:
            if path in tree:
                mismatches.append(f"path {path!r} expected to be absent but exists")

        git = spec.git or {}
        if git:
            git_mismatches = _check_git(git, state)
            mismatches.extend(git_mismatches)

        if mismatches:
            return VerifierResult(
                verdict="fail",
                score=0.0,
                reason="state_check mismatch: " + "; ".join(mismatches),
                details={**details, "mismatches": mismatches},
            )
        return VerifierResult(
            verdict="pass",
            score=1.0,
            reason="state_check passed: all expected files/git/absent checks satisfied",
            details=details,
        )


def _diff_has_file(diff: str, path: str) -> bool:
    """Return True iff a unified diff section targets ``path`` exactly."""
    return any(section_path == path for section_path, _ in _iter_diff_sections(diff))


def _diff_file_contains(diff: str, path: str, needle: str) -> bool:
    """Return True if added/modified lines for exact ``path`` contain ``needle``.

    The verifier must not match path substrings in diff headers.  A diff for
    ``src/app.py.bak`` is not evidence about ``src/app.py`` merely because the
    shorter path appears as a prefix in ``+++ b/src/app.py.bak``.  We first
    split the unified diff into file sections using exact ``+++`` paths, then
    scan only hunk additions for the requested path.
    """
    for section_path, lines in _iter_diff_sections(diff):
        if section_path != path:
            continue
        in_hunk = False
        for line in lines:
            if line.startswith("@@"):
                in_hunk = True
                continue
            if line.startswith("diff --git"):
                in_hunk = False
                continue
            if in_hunk and line.startswith("+"):
                if needle in line[1:]:
                    return True
    return False


def _iter_diff_sections(diff: str) -> list[tuple[str, list[str]]]:
    """Return ``(new_path, section_lines)`` pairs from a unified diff.

    Only ``+++`` markers in the file-header prelude identify a target path:
    they must be paired with a preceding ``---`` header and appear before the
    first hunk.  In-hunk added content can legitimately start with ``+++`` and
    must remain ordinary content, not a new file section.
    """
    sections: list[tuple[str, list[str]]] = []
    current_path: str | None = None
    current_lines: list[str] = []
    awaiting_new_header = False
    in_hunk = False

    def flush() -> None:
        nonlocal current_path, current_lines, awaiting_new_header, in_hunk
        if current_path is not None:
            sections.append((current_path, current_lines))
        current_path = None
        current_lines = []
        awaiting_new_header = False
        in_hunk = False

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            flush()
            current_lines = [line]
            continue

        if not current_lines and line.startswith("--- "):
            current_lines = [line]
        elif current_lines:
            current_lines.append(line)
        else:
            continue

        if line.startswith("@@"):
            in_hunk = True
            awaiting_new_header = False
            continue
        if in_hunk:
            continue
        if line.startswith("--- "):
            awaiting_new_header = True
            continue
        if awaiting_new_header and line.startswith("+++ "):
            current_path = _parse_diff_new_path(line)
            awaiting_new_header = False
            continue
        if awaiting_new_header and line.strip():
            awaiting_new_header = False

    flush()
    return sections


def _parse_diff_new_path(line: str) -> str | None:
    marker = line[4:].strip()
    if marker == "/dev/null":
        return None
    if marker.startswith("b/"):
        return marker[2:]
    return marker or None


def _check_git(git: Mapping[str, Any], state: RepoState) -> list[str]:
    mismatches: list[str] = []
    branches = git.get("branches")
    if branches is not None:
        expected_branches = set(branches)
        actual_branches = set(state.branches)
        missing = expected_branches - actual_branches
        if missing:
            mismatches.append(
                f"git branches missing: {sorted(missing)} "
                f"(present: {sorted(actual_branches)})"
            )
    commits = git.get("commits")
    if commits is not None:
        for sha_prefix, subject_substr in commits.items():
            if not _commit_matches(state.commits, sha_prefix, subject_substr):
                mismatches.append(
                    f"git commit {sha_prefix!r} (subject containing "
                    f"{subject_substr!r}) not found in snapshot commits"
                )
    if git.get("status_clean"):
        if state.git_status.strip():
            mismatches.append(
                f"git status expected clean but is: {state.git_status!r}"
            )
    head_msg = git.get("head_commit_message")
    if head_msg is not None:
        if not state.commits:
            mismatches.append(
                "git head_commit_message expected but snapshot has no commits"
            )
        elif head_msg not in state.commits[0].get("subject", ""):
            mismatches.append(
                f"git head commit subject {state.commits[0].get('subject')!r} "
                f"does not contain {head_msg!r}"
            )
    return mismatches


def _commit_matches(
    commits: Sequence[Mapping[str, str]], sha_prefix: str, subject_substr: str
) -> bool:
    for commit in commits:
        sha = commit.get("sha", "")
        subject = commit.get("subject", "")
        if sha.startswith(sha_prefix) or sha_prefix.startswith(sha):
            if not subject_substr or subject_substr in subject:
                return True
    return False


_DEFAULT_STATE_CHECK_IMPL: StateCheckVerifier | None = None


def _default_state_check_impl() -> StateCheckVerifier:
    """Return (and cache) the C07.2 default repo-state verifier.

    Registered lazily so importing ``scoring`` does not require the sandbox
    module. The default impl is a plain :class:`RepoStateVerifier` with no
    filesystem dependency.
    """
    global _DEFAULT_STATE_CHECK_IMPL
    if _DEFAULT_STATE_CHECK_IMPL is None:
        _DEFAULT_STATE_CHECK_IMPL = RepoStateVerifier()
    return _DEFAULT_STATE_CHECK_IMPL


# --- LLM-judge verifier -----------------------------------------------------


@runtime_checkable
class LLMJudge(Protocol):
    """Interface for an LLM-judge adapter.

    A real adapter is wired by the runner (C05) using a pinned judge model.
    Tests use :class:`MockLLMJudge` instead. ``judge`` returns a
    ``(verdict, score, reason)`` tuple.
    """

    def judge(
        self,
        config: LLMJudgeConfig,
        expected: Any,
        observed: Any,
    ) -> tuple[Verdict, float, str]:
        ...


def llm_judge(
    expected: Any, observed: Any, params: Mapping[str, Any]
) -> VerifierResult:
    """LLM-judge verifier requiring a pinned judge configuration.

    ``params`` must carry:
      * ``judge_config`` -- a pinned :class:`LLMJudgeConfig` or mapping with
        ``judge_model``, ``judge_prompt``, ``judge_params``, ``judge_seed``.
        Missing or unpinned fields raise :class:`VerifierConfigurationError`;
        the LLM-judge path cannot run without pinned metadata.
      * ``judge`` -- an :class:`LLMJudge` adapter. The real adapter is wired
        by the runner (C05); tests pass :class:`MockLLMJudge`.

    The returned :class:`VerifierResult` records the pinned ``judge_model`` and
    ``judge_seed`` in ``details`` for run-record provenance.
    """
    cfg = _resolve_judge_config(params)
    judge = params.get("judge")
    if judge is None:
        raise VerifierConfigurationError(
            "llm_judge requires a judge adapter (params['judge']); the real "
            "adapter is wired by the runner (C05); use MockLLMJudge for tests"
        )
    try:
        verdict, score, reason = judge.judge(cfg, expected, observed)  # type: ignore[attr-defined]
    except VerifierError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise VerifierError(f"llm_judge adapter raised: {exc}") from exc
    if verdict not in ("pass", "fail"):
        raise VerifierError(
            f"llm_judge adapter returned invalid verdict {verdict!r}"
        )
    if not 0.0 <= float(score) <= 1.0:
        raise VerifierError(
            f"llm_judge adapter returned score outside [0, 1]: {score}"
        )
    return VerifierResult(
        verdict=verdict,
        score=float(score),
        reason=reason,
        details={
            "judge_model": cfg.judge_model,
            "judge_seed": cfg.judge_seed,
            "judge_params": dict(cfg.judge_params),
        },
    )


class MockLLMJudge:
    """Deterministic LLM-judge mock for tests only.

    Not for production runs. The verdict is exact string equality (after
    strip + lowercase) between expected and observed, so the mock is fully
    deterministic and independent of any model provider. It still requires a
    pinned judge config to flow through :func:`llm_judge`, exercising the
    "cannot run without pinned metadata" contract.
    """

    def judge(
        self,
        config: LLMJudgeConfig,
        expected: Any,
        observed: Any,
    ) -> tuple[Verdict, float, str]:
        exp = _to_str(expected).strip().lower()
        obs = _to_str(observed).strip().lower()
        ok = exp == obs
        return (
            "pass" if ok else "fail",
            1.0 if ok else 0.0,
            "mock llm judge: deterministic exact equality",
        )


# --- Registry ---------------------------------------------------------------

# Closed, fixed registry of built-in verifiers. v1 does NOT support arbitrary
# dotted-path custom code execution: there is no importlib/getattr verifier
# resolution. New verifiers require a schema/types change owned by C13.
VERIFIERS: Mapping[str, VerifierFn] = {
    "exact_match": exact_match,
    "contains_any": contains_any,
    "regex_match": regex_match,
    "set_f1": set_f1,
    "state_check": state_check,
    "llm_judge": llm_judge,
}


def get_verifier(name: str) -> VerifierFn:
    """Return the built-in verifier function for ``name``.

    Raises :class:`VerifierNotFoundError` for unknown names. v1 supports only
    the closed set in :data:`VERIFIERS`; no dotted-path resolution is used.
    """
    fn = VERIFIERS.get(name)
    if fn is None:
        raise VerifierNotFoundError(
            f"unknown verifier {name!r}; v1 supports {sorted(VERIFIERS)}"
        )
    return fn


# --- score_case + aggregate -------------------------------------------------


def _resolve_verifier_name(
    case: CaseDefinition, metric: MetricConfig | None
) -> VerifierName:
    if case.verifier is not None:
        return case.verifier.verifier
    if metric is not None:
        return metric.verifier
    raise VerifierConfigurationError(
        f"case {case.id!r} has no per-case verifier and no benchmark metric "
        "was provided"
    )


def _merge_params(
    metric: MetricConfig | None, case: CaseDefinition
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if metric is not None:
        merged.update(metric.params)
    if case.verifier is not None:
        merged.update(case.verifier.params)
    return merged


def score_case(
    case: CaseDefinition,
    observed: Any,
    *,
    metric: MetricConfig | None = None,
    benchmark_llm_judge: LLMJudgeConfig | None = None,
) -> CaseVerdict:
    """Score a single case against an observed output.

    The verifier is resolved from ``case.verifier`` (per-case override) or
    ``metric`` (benchmark-level default). Params are merged benchmark-first,
    then per-case override. For ``llm_judge``, the pinned judge config is
    resolved from ``case.llm_judge`` or ``benchmark_llm_judge`` and injected
    into the merged params as ``judge_config``; the caller (runner/tests) is
    expected to supply the ``judge`` adapter via the merged params.

    For text verifiers, a null ``expected`` raises
    :class:`VerifierConfigurationError` (null expected is permitted only for
    preserved failure cases, which are not scored as normal cases). For
    ``state_check``, ``case.state_check`` is the expected spec and
    ``observed`` is a :class:`RepoState`.

    Verifier exceptions propagate to the caller; the runner (C05) maps them to
    non-zero process failures or per-case ``error`` fields per its exit
    contract.
    """
    vname = _resolve_verifier_name(case, metric)
    params = _merge_params(metric, case)

    expected: Any = case.expected
    if vname == "state_check":
        expected = case.state_check
        if expected is None:
            raise VerifierConfigurationError(
                f"case {case.id!r} uses the state_check verifier but has no "
                "state_check spec"
            )
    elif vname in _TEXT_VERIFIERS and expected is None:
        raise VerifierConfigurationError(
            f"case {case.id!r} has a null expected value; the {vname} verifier "
            "cannot score a preserved failure case as a normal case "
            "(expected_metadata is required for null-expected cases)"
        )

    if vname == "llm_judge":
        jcfg = case.llm_judge or benchmark_llm_judge
        if jcfg is not None:
            params["judge_config"] = jcfg

    fn = get_verifier(vname)
    result = fn(expected, observed, params)
    return CaseVerdict(
        case_id=case.id,
        verdict=result.verdict,
        score=result.score,
        verifier=vname,
        reason=result.reason,
        details=dict(result.details),
        expected=expected,
        observed=observed,
        error=None,
    )


def score_cases(
    cases: Sequence[CaseDefinition],
    observed_by_id: Mapping[str, Any],
    *,
    metric: MetricConfig | None = None,
    benchmark_llm_judge: LLMJudgeConfig | None = None,
) -> tuple[list[CaseVerdict], AggregateScore]:
    """Score a sequence of cases and return ``(verdicts, aggregate)``.

    ``observed_by_id`` maps case id -> observed output. A case id missing from
    the mapping raises :class:`VerifierConfigurationError` (the caller must
    supply an observation for every selected case). The aggregate ``metric``
    label is the resolved verifier name when ``metric`` is provided, else
    ``"mixed"``.
    """
    verdicts: list[CaseVerdict] = []
    for case in cases:
        if case.id not in observed_by_id:
            raise VerifierConfigurationError(
                f"no observed output provided for case {case.id!r}"
            )
        verdicts.append(
            score_case(
                case,
                observed_by_id[case.id],
                metric=metric,
                benchmark_llm_judge=benchmark_llm_judge,
            )
        )
    metric_label = metric.verifier if metric is not None else "mixed"
    aggregate = aggregate_scores(verdicts, metric=metric_label)
    return verdicts, aggregate


def aggregate_scores(
    verdicts: Sequence[CaseVerdict], *, metric: str
) -> AggregateScore:
    """Aggregate per-case verdicts into an :class:`AggregateScore`.

    ``value`` is the mean score over the verdicts (``0.0`` when empty).
    ``n_pass``/``n_fail`` count verdicts by label. An empty input yields
    ``n_cases=0`` and ``value=0.0``.
    """
    n = len(verdicts)
    total = sum(v.score for v in verdicts)
    value = (total / n) if n else 0.0
    n_pass = sum(1 for v in verdicts if v.verdict == "pass")
    n_fail = sum(1 for v in verdicts if v.verdict == "fail")
    return AggregateScore(
        metric=metric,
        value=value,
        n_cases=n,
        n_pass=n_pass,
        n_fail=n_fail,
        details={},
    )
