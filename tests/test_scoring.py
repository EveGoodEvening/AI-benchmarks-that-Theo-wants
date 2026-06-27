"""Scoring/verifier engine tests for chunk C04.

Covers the built-in deterministic verifiers (exact_match, contains_any,
regex_match, set_f1), the state_check interface shape, the llm_judge pinned
config contract + MockLLMJudge, and the score_case / aggregate helpers.

Edge cases required by the C04 review criteria:
  * empty expected sets, extra whitespace, regex mismatch, full/partial
    set-F1, and null expected failure cases.
  * LLM-judge path cannot run without pinned metadata.
  * No arbitrary dotted-path custom code execution (closed registry).
"""

from __future__ import annotations

from typing import Any

import pytest

from ai_bench import types as T
from ai_bench.scoring import (
    CaseVerdict,
    MockLLMJudge,
    RepoStateVerifier,
    VERIFIERS,
    VERIFIER_VERSION,
    VerifierConfigurationError,
    VerifierError,
    VerifierNotFoundError,
    VerifierResult,
    aggregate_scores,
    contains_any,
    exact_match,
    get_verifier,
    llm_judge,
    register_state_check_verifier,
    regex_match,
    score_case,
    score_cases,
    set_f1,
    state_check,
)


# --- Shared case builders ---------------------------------------------------


def _metric(verifier: str, **params: Any) -> T.MetricConfig:
    return T.MetricConfig(verifier=verifier, params=dict(params))


def _case(
    cid: str = "c1",
    expected: Any = "hello",
    verifier: T.CaseVerifierOverride | None = None,
    state_check: T.StateCheckSpec | None = None,
    llm_judge: T.LLMJudgeConfig | None = None,
) -> T.CaseDefinition:
    return T.CaseDefinition(
        schema_version="1",
        id=cid,
        input="prompt",
        expected=expected,
        tags=(),
        difficulty="medium",
        provenance=T.Provenance(source="original", license="MIT"),
        verifier=verifier,
        state_check=state_check,
        llm_judge=llm_judge,
    )


def _judge_cfg(**overrides: Any) -> T.LLMJudgeConfig:
    base: dict[str, Any] = {
        "judge_model": "mock-judge-1",
        "judge_prompt": "Is the answer correct?",
        "judge_seed": "seed-42",
        "judge_params": {"temperature": 0.0},
    }
    base.update(overrides)
    return T.LLMJudgeConfig(**base)


# --- exact_match ------------------------------------------------------------


class TestExactMatch:
    def test_case_insensitive_default_pass(self) -> None:
        r = exact_match("Hello", "hello", {})
        assert r.verdict == "pass"
        assert r.score == 1.0
        assert "exact match" in r.reason

    def test_case_sensitive_mismatch(self) -> None:
        r = exact_match("Hello", "hello", {"case_sensitive": True})
        assert r.verdict == "fail"
        assert r.score == 0.0

    def test_case_sensitive_pass(self) -> None:
        r = exact_match("Hello", "Hello", {"case_sensitive": True})
        assert r.verdict == "pass"

    def test_trim_default_strips_whitespace(self) -> None:
        r = exact_match("  hello  ", "hello\n", {})
        assert r.verdict == "pass"

    def test_trim_disabled(self) -> None:
        r = exact_match("  hello  ", "  hello  ", {"trim": False})
        assert r.verdict == "pass"
        r2 = exact_match(" hello ", "hello", {"trim": False})
        assert r2.verdict == "fail"

    def test_normalize_whitespace(self) -> None:
        r = exact_match("hello   world", "hello world", {"normalize_whitespace": True})
        assert r.verdict == "pass"
        # Without normalization the extra spaces differ.
        r2 = exact_match("hello   world", "hello world", {})
        assert r2.verdict == "fail"

    def test_non_string_coerced(self) -> None:
        r = exact_match(42, "42", {})
        assert r.verdict == "pass"

    def test_boolean_lowercase(self) -> None:
        r = exact_match(True, "true", {})
        assert r.verdict == "pass"
        r2 = exact_match(False, "false", {"case_sensitive": True})
        assert r2.verdict == "pass"

    def test_details_record_options(self) -> None:
        r = exact_match("a", "a", {"case_sensitive": True, "normalize_whitespace": True})
        assert r.details["case_sensitive"] is True
        assert r.details["normalize_whitespace"] is True
        assert r.details["expected"] == "a"
        assert r.details["observed"] == "a"


# --- contains_any -----------------------------------------------------------


class TestContainsAny:
    def test_default_needle_from_expected_string(self) -> None:
        r = contains_any("cat", "the cat sat", {})
        assert r.verdict == "pass"
        assert r.score == 1.0

    def test_needle_list_from_expected(self) -> None:
        r = contains_any(["cat", "dog"], "a dog", {})
        assert r.verdict == "pass"

    def test_params_needles_override(self) -> None:
        r = contains_any("ignored", "a dog", {"needles": ["cat", "dog"]})
        assert r.verdict == "pass"

    def test_params_needles_scalar_string_is_one_needle(self) -> None:
        r = contains_any("ignored", "a", {"needles": "cat"})
        assert r.verdict == "fail"
        assert r.details["needles"] == ["cat"]
        assert r.details["matched"] == []

    def test_no_match(self) -> None:
        r = contains_any(["cat", "dog"], "a fish", {})
        assert r.verdict == "fail"
        assert r.details["matched"] == []

    def test_case_sensitive(self) -> None:
        r = contains_any("Cat", "the cat", {"case_sensitive": True})
        assert r.verdict == "fail"
        r2 = contains_any("Cat", "the Cat", {"case_sensitive": True})
        assert r2.verdict == "pass"

    def test_empty_needles_ignored(self) -> None:
        r = contains_any(["", "  "], "anything", {"trim": True})
        # After trim the needles become empty strings and are ignored.
        assert r.verdict == "fail"

    def test_trim_default(self) -> None:
        r = contains_any("  cat  ", "the cat", {})
        assert r.verdict == "pass"



# --- Shared boolean param validation ----------------------------------------


class TestBooleanVerifierParams:
    @pytest.mark.parametrize(
        ("fn", "expected", "observed", "params"),
        [
            (exact_match, "Hello", "hello", {"case_sensitive": "false"}),
            (exact_match, " hello ", "hello", {"trim": "false"}),
            (exact_match, "hello   world", "hello world", {"normalize_whitespace": "true"}),
            (contains_any, "Cat", "the cat", {"case_sensitive": "false"}),
            (contains_any, " cat ", "the cat", {"trim": "false"}),
            (regex_match, "a", "a", {"fullmatch": "true"}),
            (set_f1, "A", "a", {"case_sensitive": "false"}),
        ],
    )
    def test_rejects_string_boolean_params(
        self,
        fn: Any,
        expected: Any,
        observed: Any,
        params: dict[str, Any],
    ) -> None:
        with pytest.raises(VerifierConfigurationError, match="must be a bool"):
            fn(expected, observed, params)

# --- regex_match ------------------------------------------------------------


class TestRegexMatch:
    def test_search_default_pass(self) -> None:
        r = regex_match(r"\d{3}", "abc123def", {})
        assert r.verdict == "pass"
        assert r.details["match_span"] == [3, 6]

    def test_search_mismatch(self) -> None:
        r = regex_match(r"\d{3}", "abcdef", {})
        assert r.verdict == "fail"
        assert r.details["match_span"] is None

    def test_fullmatch_required(self) -> None:
        r = regex_match(r"\d{3}", "abc123def", {"fullmatch": True})
        assert r.verdict == "fail"
        r2 = regex_match(r"\d{3}", "123", {"fullmatch": True})
        assert r2.verdict == "pass"

    def test_pattern_from_params(self) -> None:
        r = regex_match("ignored", "abc", {"pattern": "^abc$"})
        assert r.verdict == "pass"

    def test_flags_ignorecase(self) -> None:
        r = regex_match("hello", "HELLO", {"fullmatch": True, "flags": "ignorecase"})
        assert r.verdict == "pass"

    def test_flags_list(self) -> None:
        r = regex_match(
            "hello.world", "hello\nworld", {"fullmatch": True, "flags": ["dotall", "ignorecase"]}
        )
        assert r.verdict == "pass"

    def test_invalid_pattern_raises(self) -> None:
        with pytest.raises(VerifierConfigurationError, match="invalid regex"):
            regex_match("(unclosed", "abc", {})

    def test_empty_pattern_raises(self) -> None:
        with pytest.raises(VerifierConfigurationError, match="non-empty"):
            regex_match("", "abc", {})

    def test_unknown_flag_raises(self) -> None:
        with pytest.raises(VerifierConfigurationError, match="unknown flag"):
            regex_match("a", "a", {"flags": "bogus"})


# --- set_f1 -----------------------------------------------------------------


class TestSetF1:
    def test_perfect_match(self) -> None:
        r = set_f1("a b c", "c b a", {})
        assert r.verdict == "pass"
        assert r.score == 1.0
        assert sorted(r.details["intersection"]) == ["a", "b", "c"]

    def test_partial_f1(self) -> None:
        # expected {a,b,c,d}, observed {a,b,c,e}: tp=3, P=3/4, R=3/4, F1=0.75
        r = set_f1("a b c d", "a b c e", {})
        assert r.score == pytest.approx(0.75)
        assert r.verdict == "fail"  # default threshold 1.0

    def test_threshold_pass(self) -> None:
        r = set_f1("a b c d", "a b c e", {"threshold": 0.7})
        assert r.verdict == "pass"
        assert r.score == pytest.approx(0.75)

    def test_no_intersection(self) -> None:
        r = set_f1("a b", "c d", {})
        assert r.score == 0.0
        assert r.verdict == "fail"

    def test_both_empty_sets_score_one(self) -> None:
        r = set_f1("", "", {})
        assert r.score == 1.0
        assert r.verdict == "pass"

    def test_one_empty_set_score_zero(self) -> None:
        r = set_f1("a b", "", {})
        assert r.score == 0.0
        assert r.verdict == "fail"
        r2 = set_f1("", "a b", {})
        assert r2.score == 0.0

    def test_case_sensitive(self) -> None:
        r = set_f1("A B", "a b", {"case_sensitive": True})
        assert r.score == 0.0
        r2 = set_f1("A B", "a b", {"case_sensitive": False})
        assert r2.score == 1.0

    def test_custom_delimiter(self) -> None:
        r = set_f1("a,b,c", "a,b", {"delimiter": ","})
        # tp=2, P=2/2, R=2/3, F1 = 2*1*0.6667/1.6667 = 0.8
        assert r.score == pytest.approx(2 / 3 * 2 / (1 + 2 / 3))

    def test_list_input(self) -> None:
        r = set_f1(["a", "b"], ["a", "b"], {})
        assert r.score == 1.0

    def test_invalid_threshold_raises(self) -> None:
        with pytest.raises(VerifierConfigurationError, match="threshold"):
            set_f1("a", "a", {"threshold": 1.5})

    def test_invalid_delimiter_raises(self) -> None:
        with pytest.raises(VerifierConfigurationError, match="delimiter"):
            set_f1("a", "a", {"delimiter": ""})

    def test_null_expected_raises(self) -> None:
        with pytest.raises(VerifierConfigurationError, match="expected is null"):
            set_f1(None, "a", {})


# --- state_check interface shape --------------------------------------------


class _RecordingStateCheckVerifier:
    def __init__(self, return_result: VerifierResult) -> None:
        self._return = return_result
        self.calls: list[tuple[T.StateCheckSpec, T.RepoState, dict[str, Any]]] = []

    def check(
        self,
        spec: T.StateCheckSpec,
        state: T.RepoState,
        params: dict[str, Any],
    ) -> VerifierResult:
        self.calls.append((spec, state, dict(params)))
        return self._return


def _repo_state(**overrides: Any) -> T.RepoState:
    base: dict[str, Any] = {
        "file_tree": ("a.txt",),
        "git_status": "",
        "branches": ("main",),
        "commits": ({"sha": "abcdef0", "subject": "init"},),
        "diff": "",
    }
    base.update(overrides)
    return T.RepoState(**base)  # type: ignore[arg-type]


class TestStateCheck:
    def test_not_implemented_without_registration(self) -> None:
        register_state_check_verifier(None)  # type: ignore[arg-type]
        spec = T.StateCheckSpec(files={"a.txt": {"exists": True}})
        with pytest.raises(NotImplementedError, match="C07"):
            state_check(spec, _repo_state(), {})

    def test_registered_impl_invoked(self) -> None:
        result = VerifierResult(verdict="pass", score=1.0, reason="ok")
        impl = _RecordingStateCheckVerifier(result)
        register_state_check_verifier(impl)  # type: ignore[arg-type]
        try:
            spec = T.StateCheckSpec(files={"a.txt": {"exists": True}})
            state = _repo_state()
            out = state_check(spec, state, {"strict": True})
            assert out is result
            assert len(impl.calls) == 1
            assert impl.calls[0][0] is spec
            assert impl.calls[0][1] is state
            assert impl.calls[0][2] == {"strict": True}
        finally:
            register_state_check_verifier(None)  # type: ignore[arg-type]

    def test_mapping_inputs_coerced(self) -> None:
        result = VerifierResult(verdict="fail", score=0.0, reason="nope")
        impl = _RecordingStateCheckVerifier(result)
        register_state_check_verifier(impl)  # type: ignore[arg-type]
        try:
            spec_map = {"files": {"a.txt": {"exists": True}}, "absent": ["b.txt"]}
            state_map = {
                "file_tree": ["a.txt"],
                "git_status": "",
                "branches": ["main"],
                "commits": [{"sha": "abcdef0", "subject": "init"}],
                "diff": "",
            }
            out = state_check(spec_map, state_map, {})  # type: ignore[arg-type]
            assert out is result
            assert isinstance(impl.calls[0][0], T.StateCheckSpec)
            assert isinstance(impl.calls[0][1], T.RepoState)
        finally:
            register_state_check_verifier(None)  # type: ignore[arg-type]

    def test_missing_repo_state_field_raises(self) -> None:
        with pytest.raises(VerifierConfigurationError, match="missing fields"):
            state_check(T.StateCheckSpec(), {"file_tree": []}, {})  # type: ignore[arg-type]

    def test_diff_in_hunk_plus_header_line_does_not_change_target_file(self) -> None:
        """An added ``+++ b/target`` line in another file is hunk content."""
        diff = "\n".join(
            [
                "diff --git a/other.txt b/other.txt",
                "index 0000000..1111111 100644",
                "--- a/other.txt",
                "+++ b/other.txt",
                "@@ -0,0 +1,2 @@",
                "+++ b/target.txt",
                "+needle-from-other-file",
            ]
        )
        state = _repo_state(file_tree=("target.txt", "other.txt"), diff=diff)
        spec = T.StateCheckSpec(
            files={"target.txt": {"exists": True, "contains": "needle-from-other-file"}}
        )
        result = RepoStateVerifier().check(spec, state, {})
        assert result.verdict == "fail"
        assert result.score == 0.0
        assert "target.txt" in result.reason
        assert "cannot be verified" in result.reason


# --- llm_judge --------------------------------------------------------------


class TestLLMJudge:
    def test_requires_judge_config(self) -> None:
        with pytest.raises(VerifierConfigurationError, match="pinned judge_config"):
            llm_judge("a", "a", {"judge": MockLLMJudge()})

    def test_mapping_judge_config_accepted(self) -> None:
        cfg = {
            "judge_model": "m",
            "judge_prompt": "p",
            "judge_params": {},
            "judge_seed": "s",
        }
        r = llm_judge("a", "a", {"judge_config": cfg, "judge": MockLLMJudge()})
        assert r.verdict == "pass"
        assert r.details["judge_model"] == "m"
        assert r.details["judge_seed"] == "s"

    def test_mapping_judge_config_requires_explicit_judge_params(self) -> None:
        cfg = {
            "judge_model": "m",
            "judge_prompt": "p",
            "judge_seed": "s",
        }
        with pytest.raises(VerifierConfigurationError, match="judge_params"):
            llm_judge("a", "a", {"judge_config": cfg, "judge": MockLLMJudge()})

    def test_missing_judge_model_raises(self) -> None:
        cfg = {"judge_model": "", "judge_prompt": "p", "judge_params": {}, "judge_seed": "s"}
        with pytest.raises(VerifierConfigurationError, match="judge_model"):
            llm_judge("a", "a", {"judge_config": cfg, "judge": MockLLMJudge()})

    def test_missing_judge_prompt_raises(self) -> None:
        cfg = {"judge_model": "m", "judge_prompt": "", "judge_params": {}, "judge_seed": "s"}
        with pytest.raises(VerifierConfigurationError, match="judge_prompt"):
            llm_judge("a", "a", {"judge_config": cfg, "judge": MockLLMJudge()})

    def test_missing_judge_seed_raises(self) -> None:
        cfg = {"judge_model": "m", "judge_prompt": "p", "judge_params": {}, "judge_seed": None}
        with pytest.raises(VerifierConfigurationError, match="judge_seed"):
            llm_judge("a", "a", {"judge_config": cfg, "judge": MockLLMJudge()})

    def test_non_mapping_judge_params_raises(self) -> None:
        cfg = {"judge_model": "m", "judge_prompt": "p", "judge_params": [], "judge_seed": "s"}
        with pytest.raises(VerifierConfigurationError, match="judge_params"):
            llm_judge("a", "a", {"judge_config": cfg, "judge": MockLLMJudge()})

    def test_requires_judge_adapter(self) -> None:
        cfg = _judge_cfg()
        with pytest.raises(VerifierConfigurationError, match="judge adapter"):
            llm_judge("a", "a", {"judge_config": cfg})

    def test_mock_judge_deterministic(self) -> None:
        cfg = _judge_cfg()
        r1 = llm_judge("hello", "Hello", {"judge_config": cfg, "judge": MockLLMJudge()})
        r2 = llm_judge("hello", "Hello", {"judge_config": cfg, "judge": MockLLMJudge()})
        assert r1.verdict == "pass"
        assert r1 == r2
        assert "mock llm judge" in r1.reason

    def test_mock_judge_fail(self) -> None:
        cfg = _judge_cfg()
        r = llm_judge("hello", "world", {"judge_config": cfg, "judge": MockLLMJudge()})
        assert r.verdict == "fail"
        assert r.score == 0.0

    def test_invalid_verdict_from_adapter_raises(self) -> None:
        class Bad:
            def judge(self, config, expected, observed):
                return ("maybe", 0.5, "x")  # type: ignore[return-value]

        cfg = _judge_cfg()
        with pytest.raises(VerifierError, match="invalid verdict"):
            llm_judge("a", "a", {"judge_config": cfg, "judge": Bad()})  # type: ignore[arg-type]

    def test_score_out_of_range_raises(self) -> None:
        class Bad:
            def judge(self, config, expected, observed):
                return ("pass", 1.5, "x")  # type: ignore[return-value]

        cfg = _judge_cfg()
        with pytest.raises(VerifierError, match="outside \\[0, 1\\]"):
            llm_judge("a", "a", {"judge_config": cfg, "judge": Bad()})  # type: ignore[arg-type]


# --- registry ---------------------------------------------------------------


class TestRegistry:
    def test_all_six_verifiers_registered(self) -> None:
        assert set(VERIFIERS) == {
            "exact_match",
            "contains_any",
            "regex_match",
            "set_f1",
            "state_check",
            "llm_judge",
        }

    def test_get_verifier_returns_callable(self) -> None:
        assert get_verifier("exact_match") is exact_match

    def test_unknown_verifier_raises(self) -> None:
        with pytest.raises(VerifierNotFoundError, match="unknown verifier"):
            get_verifier("nope")

    def test_no_dotted_path_resolution(self) -> None:
        # The registry is a closed mapping; a dotted path is not a verifier.
        with pytest.raises(VerifierNotFoundError):
            get_verifier("os.system")

    def test_verifier_version_is_string(self) -> None:
        assert isinstance(VERIFIER_VERSION, str)
        assert VERIFIER_VERSION


# --- score_case + aggregate -------------------------------------------------


class TestScoreCase:
    def test_uses_benchmark_metric(self) -> None:
        case = _case("c1", expected="hello")
        v = score_case(case, "hello", metric=_metric("exact_match"))
        assert v.verdict == "pass"
        assert v.verifier == "exact_match"
        assert v.case_id == "c1"
        assert v.error is None
        assert v.expected == "hello"
        assert v.observed == "hello"

    def test_per_case_override_wins(self) -> None:
        case = _case(
            "c1",
            expected="cat",
            verifier=T.CaseVerifierOverride(verifier="contains_any"),
        )
        v = score_case(case, "the cat sat", metric=_metric("exact_match"))
        assert v.verifier == "contains_any"
        assert v.verdict == "pass"

    def test_params_merged_benchmark_then_case(self) -> None:
        # Benchmark says case_sensitive True; case override says False.
        case = _case(
            "c1",
            expected="Hello",
            verifier=T.CaseVerifierOverride(
                verifier="exact_match", params={"case_sensitive": False}
            ),
        )
        v = score_case(
            case, "hello", metric=_metric("exact_match", case_sensitive=True)
        )
        assert v.verdict == "pass"

    def test_null_expected_text_verifier_raises(self) -> None:
        case = _case("c1", expected=None)
        with pytest.raises(VerifierConfigurationError, match="null expected"):
            score_case(case, "x", metric=_metric("exact_match"))

    def test_no_verifier_configured_raises(self) -> None:
        case = _case("c1", expected="x")
        with pytest.raises(VerifierConfigurationError, match="no per-case verifier"):
            score_case(case, "x")

    def test_state_check_case_uses_state_spec(self) -> None:
        result = VerifierResult(verdict="pass", score=1.0, reason="ok")
        impl = _RecordingStateCheckVerifier(result)
        register_state_check_verifier(impl)  # type: ignore[arg-type]
        try:
            spec = T.StateCheckSpec(files={"a.txt": {"exists": True}})
            case = _case(
                "c1",
                expected="ignored",
                verifier=T.CaseVerifierOverride(verifier="state_check"),
                state_check=spec,
            )
            state = _repo_state()
            v = score_case(case, state)
            assert v.verifier == "state_check"
            assert v.verdict == "pass"
            assert v.expected is spec
            assert v.observed is state
        finally:
            register_state_check_verifier(None)  # type: ignore[arg-type]

    def test_state_check_case_without_spec_raises(self) -> None:
        case = _case(
            "c1",
            expected="ignored",
            verifier=T.CaseVerifierOverride(verifier="state_check"),
            state_check=None,
        )
        with pytest.raises(VerifierConfigurationError, match="no state_check spec"):
            score_case(case, _repo_state())

    def test_llm_judge_case_uses_case_judge_config(self) -> None:
        jcfg = _judge_cfg()
        case = _case(
            "c1",
            expected="hello",
            verifier=T.CaseVerifierOverride(verifier="llm_judge"),
            llm_judge=jcfg,
        )
        v = score_case(
            case,
            "Hello",
            metric=_metric("llm_judge", judge=MockLLMJudge()),
        )
        assert v.verifier == "llm_judge"
        assert v.verdict == "pass"

    def test_llm_judge_case_falls_back_to_benchmark_judge(self) -> None:
        bjcfg = _judge_cfg()
        case = _case(
            "c1",
            expected="hello",
            verifier=T.CaseVerifierOverride(verifier="llm_judge"),
            llm_judge=None,
        )
        v = score_case(
            case,
            "Hello",
            metric=_metric("llm_judge", judge=MockLLMJudge()),
            benchmark_llm_judge=bjcfg,
        )
        assert v.verdict == "pass"

    def test_llm_judge_without_pinned_config_raises(self) -> None:
        case = _case(
            "c1",
            expected="hello",
            verifier=T.CaseVerifierOverride(verifier="llm_judge"),
            llm_judge=None,
        )
        with pytest.raises(VerifierConfigurationError, match="pinned judge_config"):
            score_case(case, "hello", metric=_metric("llm_judge", judge=MockLLMJudge()))


class TestScoreCases:
    def test_aggregates_all(self) -> None:
        cases = [
            _case("a", expected="x"),
            _case("b", expected="y"),
            _case("c", expected="z"),
        ]
        observed = {"a": "x", "b": "y", "c": "wrong"}
        verdicts, agg = score_cases(cases, observed, metric=_metric("exact_match"))
        assert len(verdicts) == 3
        assert agg.metric == "exact_match"
        assert agg.n_cases == 3
        assert agg.n_pass == 2
        assert agg.n_fail == 1
        assert agg.value == pytest.approx(2 / 3)

    def test_missing_observation_raises(self) -> None:
        cases = [_case("a", expected="x"), _case("b", expected="y")]
        with pytest.raises(VerifierConfigurationError, match="no observed output"):
            score_cases(cases, {"a": "x"}, metric=_metric("exact_match"))

    def test_mixed_metric_label(self) -> None:
        cases = [
            _case("a", expected="x", verifier=T.CaseVerifierOverride(verifier="exact_match")),
            _case("b", expected="y", verifier=T.CaseVerifierOverride(verifier="contains_any")),
        ]
        verdicts, agg = score_cases(cases, {"a": "x", "b": "y"})
        assert agg.metric == "mixed"
        assert agg.n_pass == 2


class TestAggregateScores:
    def test_empty(self) -> None:
        agg = aggregate_scores([], metric="exact_match")
        assert agg.n_cases == 0
        assert agg.value == 0.0
        assert agg.n_pass == 0
        assert agg.n_fail == 0

    def test_mean_score(self) -> None:
        vs = [
            CaseVerdict("a", "pass", 1.0, "exact_match", "", {}, "x", "x"),
            CaseVerdict("b", "fail", 0.0, "exact_match", "", {}, "y", "z"),
            CaseVerdict("c", "pass", 0.5, "set_f1", "", {}, "p q", "p"),
        ]
        agg = aggregate_scores(vs, metric="mixed")
        assert agg.n_cases == 3
        assert agg.n_pass == 2
        assert agg.n_fail == 1
        assert agg.value == pytest.approx(0.5)


# --- Determinism / stability ------------------------------------------------


class TestDeterminism:
    def test_repeated_calls_identical(self) -> None:
        for _ in range(5):
            r = exact_match("Hello World", "hello world", {"normalize_whitespace": True})
            assert r.verdict == "pass"
            assert r.score == 1.0
            assert r.reason == "exact match"

    def test_set_f1_score_stable(self) -> None:
        prev: float | None = None
        for _ in range(10):
            r = set_f1("a b c d", "a b c e", {})
            assert prev is None or r.score == prev
            prev = r.score
