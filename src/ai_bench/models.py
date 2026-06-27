"""Model and agent adapter contracts for benchmark execution (chunk C05).

C05 owns this module so later sandbox work can plug into one stable
contract without redefining how text models, tool-task agents, structured tool
actions, or command dispatchers interact with the runner.

The adapters here are intentionally thin:

* text adapters take a rendered prompt plus sampling params and return text;
* agent adapters emit structured tool-action requests, never free-form shell;
* command dispatch is an injected interface.  The default C05 dispatcher is a
  deterministic fake used for tests and smoke plumbing only.  The enforced
  sandboxed dispatcher is implemented by C07 and plugs into the same shape.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from ai_bench import types as T
from ai_bench.loader import canonical_json

__all__ = [
    "ModelAdapterError",
    "TextModelAdapter",
    "StubTextModel",
    "ToolActionRequest",
    "SandboxHandle",
    "AgentAdapter",
    "CommandDispatcher",
    "StubAgent",
    "StubCommandDispatcher",
]


class ModelAdapterError(Exception):
    """Base error for model/agent adapter and dispatcher failures."""


@runtime_checkable
class TextModelAdapter(Protocol):
    """Thin text adapter: rendered prompt + params in, text out."""

    @property
    def model_id(self) -> str:
        """Stable model identifier pinned into run-records."""
        ...

    @property
    def provider(self) -> str | None:
        """Optional provider identifier pinned into run-records."""
        ...

    @property
    def adapter_kind(self) -> T.ModelAdapter:
        """Run-record adapter label."""
        ...

    def generate(
        self,
        prompt: str,
        *,
        params: Mapping[str, Any],
        seed: str | int | None,
    ) -> str:
        """Return a text prediction for ``prompt``."""
        ...


class StubTextModel:
    """Deterministic local text adapter for tests and smoke runs.

    The stub intentionally does not try to be correct.  It preserves the public
    runner contract -- selected cases are evaluated and scored -- while making
    the raw output a pure function of prompt, params, and seed.  That lets C05
    tests assert reproducibility without relying on network, API keys, or a
    provider's token sampler.
    """

    model_id = "stub"
    provider = "ai-bench"
    adapter_kind: T.ModelAdapter = "stub"

    def generate(
        self,
        prompt: str,
        *,
        params: Mapping[str, Any],
        seed: str | int | None,
    ) -> str:
        payload = canonical_json(
            {
                "prompt": prompt,
                "params": dict(params),
                "seed": seed,
            }
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        seed_label = "none" if seed is None else str(seed)
        return f"stub:{seed_label}:{digest}"


@dataclass(frozen=True)
class ToolActionRequest:
    """Structured tool action emitted by an agent before dispatch.

    ``command`` is the executable/tool name; ``argv`` excludes the command.
    ``cwd`` is relative to the per-case sandbox root.  ``env_overrides`` is the
    complete set of requested additions/overrides; C07's dispatcher decides
    which entries survive its allowlist.  ``timeout_ms`` is a request-level
    limit consumed by the dispatcher and not serialized directly because the
    C02 run-record schema records the outcome via ``wall_clock_ms`` and
    ``timeout``.
    """

    command: str
    argv: Sequence[str] = ()
    cwd: str = "."
    env_overrides: Mapping[str, str] = field(default_factory=dict)
    stdin: str | None = None
    timeout_ms: int | None = None


@dataclass(frozen=True)
class SandboxHandle:
    """Per-case sandbox handle handed to an agent.

    C05 creates the handle and copies any declared fixture into ``root`` for
    deterministic fake-dispatcher tests.  C07 replaces the dispatcher/backend
    with an enforced sandbox while preserving this handle shape.
    """

    root: Path
    case_id: str
    fixture_path: Path | None = None
    allowed_commands: Sequence[str] = ()
    env_allowlist: Sequence[str] = ()
    default_timeout_ms: int = 10_000
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class AgentAdapter(Protocol):
    """Agent adapter for tool-proficiency tasks.

    The agent receives a sandbox handle and emits structured action requests.
    The runner owns dispatch and run-record capture; an agent never receives a
    host working directory or a free-form shell.
    """

    @property
    def model_id(self) -> str:
        """Stable model/agent identifier pinned into run-records."""
        ...

    @property
    def provider(self) -> str | None:
        """Optional provider identifier pinned into run-records."""
        ...

    @property
    def adapter_kind(self) -> T.ModelAdapter:
        """Run-record adapter label."""
        ...

    def actions(
        self,
        prompt: str,
        *,
        params: Mapping[str, Any],
        sandbox: SandboxHandle,
    ) -> Iterable[ToolActionRequest]:
        """Yield structured tool-action requests for a case."""
        ...


@runtime_checkable
class CommandDispatcher(Protocol):
    """Dispatch interface consumed by the runner.

    C05's fake dispatcher implements this without executing host commands.  C07
    supplies the enforced sandboxed implementation with path/network/env/time
    confinement and the same return shape.
    """

    @property
    def backend_id(self) -> str:
        """Short backend identifier included in environment hashes."""
        ...

    def dispatch(
        self,
        action: ToolActionRequest,
        *,
        sandbox: SandboxHandle,
    ) -> T.ToolAction:
        """Run or replay one action and return the captured transcript row."""
        ...

    def snapshot(
        self,
        *,
        sandbox: SandboxHandle,
        transcript: Sequence[T.ToolAction],
    ) -> T.RepoState:
        """Return the final repo-state snapshot passed to state_check."""
        ...


class StubAgent:
    """Deterministic scripted agent for adapter-contract tests.

    A custom script may be supplied at construction time, through runner params
    as ``stub_actions``, or through the sandbox metadata (usually copied from a
    case's input object).  If no script is provided, the agent emits one git
    action and one file action so the transcript exercises both command shapes.
    """

    model_id = "stub-agent"
    provider = "ai-bench"
    adapter_kind: T.ModelAdapter = "stub"

    def __init__(self, script: Sequence[ToolActionRequest | Mapping[str, Any]] | None = None) -> None:
        self._script = tuple(_coerce_action_request(a) for a in (script or ()))

    def actions(
        self,
        prompt: str,
        *,
        params: Mapping[str, Any],
        sandbox: SandboxHandle,
    ) -> Iterable[ToolActionRequest]:
        del prompt  # The deterministic stub is script-driven, not prompt-driven.
        script = self._script
        if not script:
            raw_script = params.get("stub_actions") or sandbox.metadata.get("stub_actions")
            if raw_script:
                if not isinstance(raw_script, Sequence) or isinstance(raw_script, (str, bytes)):
                    raise ModelAdapterError("stub_actions must be a sequence of action mappings")
                script = tuple(_coerce_action_request(a) for a in raw_script)  # type: ignore[arg-type]
        if not script:
            script = (
                ToolActionRequest(command="git", argv=("status", "--short"), cwd="."),
                ToolActionRequest(
                    command="file.write",
                    argv=("README.md", "stub agent touched this fixture\n"),
                    cwd=".",
                ),
            )
        return tuple(script)


class StubCommandDispatcher:
    """Deterministic fake dispatcher that never executes host commands.

    This is not a sandbox backend and is deliberately labelled
    ``c05-fake-dispatcher`` in environment hashes.  It exists so C05 can test
    runner/adapter/run-record plumbing before C07 provides enforced dispatch.
    """

    backend_id = "c05-fake-dispatcher"

    def dispatch(
        self,
        action: ToolActionRequest,
        *,
        sandbox: SandboxHandle,
    ) -> T.ToolAction:
        del sandbox
        if not action.command:
            raise ModelAdapterError("tool action command must be non-empty")
        stdout = _fake_stdout(action)
        duration = _stable_duration_ms(action)
        return T.ToolAction(
            command=action.command,
            argv=tuple(str(a) for a in action.argv),
            cwd=action.cwd or ".",
            env_overrides={str(k): str(v) for k, v in action.env_overrides.items()},
            stdin=action.stdin,
            exit_code=0,
            stdout=stdout,
            stderr="",
            wall_clock_ms=duration,
            timeout=False,
            sandbox_boundary_violation=False,
        )

    def snapshot(
        self,
        *,
        sandbox: SandboxHandle,
        transcript: Sequence[T.ToolAction],
    ) -> T.RepoState:
        file_tree = _sandbox_file_tree(sandbox.root)
        touched = []
        for action in transcript:
            if action.command == "file.write" and action.argv:
                touched.append(str(action.argv[0]))
        merged_tree = tuple(sorted(set(file_tree).union(touched)))
        return T.RepoState(
            file_tree=merged_tree,
            git_status="",
            branches=("main",),
            commits=({"sha": "c05stub", "subject": "C05 fake dispatcher snapshot"},),
            diff="",
        )


def _coerce_action_request(raw: ToolActionRequest | Mapping[str, Any]) -> ToolActionRequest:
    if isinstance(raw, ToolActionRequest):
        return raw
    if not isinstance(raw, Mapping):
        raise ModelAdapterError(f"stub action must be a mapping, got {type(raw).__name__}")
    command = raw.get("command")
    if not isinstance(command, str) or not command:
        raise ModelAdapterError("stub action mapping requires a non-empty command")
    argv = raw.get("argv", ())
    if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)):
        raise ModelAdapterError(f"stub action {command!r} argv must be a sequence of strings")
    env = raw.get("env_overrides", {})
    if not isinstance(env, Mapping):
        raise ModelAdapterError(f"stub action {command!r} env_overrides must be a mapping")
    stdin = raw.get("stdin")
    if stdin is not None and not isinstance(stdin, str):
        raise ModelAdapterError(f"stub action {command!r} stdin must be a string or null")
    timeout_ms = raw.get("timeout_ms")
    if timeout_ms is not None and not isinstance(timeout_ms, int):
        raise ModelAdapterError(f"stub action {command!r} timeout_ms must be an integer or null")
    return ToolActionRequest(
        command=command,
        argv=tuple(str(a) for a in argv),
        cwd=str(raw.get("cwd", ".") or "."),
        env_overrides={str(k): str(v) for k, v in env.items()},
        stdin=stdin,
        timeout_ms=timeout_ms,
    )


def _stable_duration_ms(action: ToolActionRequest) -> int:
    payload = canonical_json(
        {
            "command": action.command,
            "argv": list(action.argv),
            "cwd": action.cwd,
            "env_overrides": dict(action.env_overrides),
            "stdin": action.stdin,
        }
    )
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:4], 16) % 50


def _fake_stdout(action: ToolActionRequest) -> str:
    joined = " ".join([action.command, *[str(a) for a in action.argv]]).strip()
    if action.command == "git":
        return f"c05 fake git: {joined}\n"
    if action.command.startswith("file."):
        return f"c05 fake file action: {joined}\n"
    return f"c05 fake dispatch: {joined}\n"


def _sandbox_file_tree(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    paths: list[str] = []
    for path in root.rglob("*"):
        if path.is_file():
            try:
                paths.append(path.relative_to(root).as_posix())
            except ValueError:  # pragma: no cover - defensive for odd filesystems
                continue
    return tuple(sorted(paths))
