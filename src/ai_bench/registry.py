"""Auto-discovered benchmark registry/index for ai-bench (chunk C10).

This module builds the community-facing registry/index of registered
benchmarks. It reuses the C03 loader's ``discover_benchmarks`` (which already
excludes ``benchmarks/_template/**`` and enforces unique benchmark ids) and
projects each discovered manifest into a stable ``RegistryEntry`` record
sourcing ``id``, ``domain``, ``tags``, ``contributor``, ``license``,
``status``, and ``version`` directly from the manifest fields frozen by C02 —
never inferring them ad hoc.

Scope (C10):
  * ``RegistryEntry`` dataclass: a serializable index row per benchmark.
  * ``build_registry(root)``: discover real benchmarks and return registry
    entries sorted by benchmark id for deterministic output.
  * ``registry_index(root)``: convenience returning a JSON-serializable list
    of dicts (the on-disk index shape).
  * ``format_registry(entries)``: human-readable table for the CLI.

Non-goals: the registry does not validate cases (that is the C03 validate
gate's job); it does not run benchmarks (C05); it does not write a checked-in
index file (the index is derived on demand from manifests so it can never drift
from the source of truth). The template is excluded because
``discover_benchmarks`` excludes ``benchmarks/_template/**``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai_bench import loader as L

__all__ = [
    "RegistryEntry",
    "build_registry",
    "registry_index",
    "format_registry",
]


@dataclass(frozen=True)
class RegistryEntry:
    """One registry row, sourced from a validated benchmark manifest.

    Every field is read from the manifest dict frozen by C02
    (``schemas/benchmark.schema.json``); the registry never infers metadata.
    ``dir`` is the resolved benchmark directory path (as a string) so the
    entry is JSON-serializable and points contributors at the on-disk
    benchmark.
    """

    id: str
    name: str
    domain: str
    tags: list[str] = field(default_factory=list)
    contributor: str = ""
    contributor_contact: str | None = None
    contributor_url: str | None = None
    license: str = ""
    status: str = "experimental"
    version: str = ""
    dir: str = ""

    @classmethod
    def from_manifest(cls, manifest: L.Manifest) -> "RegistryEntry":
        """Build a ``RegistryEntry`` from a loaded, validated ``Manifest``."""
        data = manifest.data
        contributor = data.get("contributor") or {}
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            domain=str(data["domain"]),
            tags=list(data.get("tags", [])),
            contributor=str(contributor.get("name", "")),
            contributor_contact=_opt_str(contributor.get("contact")),
            contributor_url=_opt_str(contributor.get("url")),
            license=str(data.get("license", "")),
            status=str(data.get("status", "experimental")),
            version=str(data.get("version", "")),
            dir=str(manifest.dir),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict view of this entry."""
        return asdict(self)


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value)
    return s or None


def build_registry(root: Path | str) -> list[RegistryEntry]:
    """Discover real benchmarks under ``<root>/benchmarks`` and build the index.

    Reuses ``loader.discover_benchmarks(root)``, which:

    * excludes ``benchmarks/_template/**`` so the template is never registered;
    * loads and schema-validates every manifest;
    * rejects duplicate benchmark ids.

    Returns registry entries sorted by benchmark id for deterministic output.
    Raises ``loader.ValidationError`` / ``loader.LoadError`` on discovery
    failure (propagated to the caller, typically the CLI).
    """
    manifests = L.discover_benchmarks(root)
    entries = [RegistryEntry.from_manifest(m) for m in manifests]
    entries.sort(key=lambda e: e.id)
    return entries


def registry_index(root: Path | str) -> list[dict[str, Any]]:
    """Return the registry as a JSON-serializable list of dicts."""
    return [e.to_dict() for e in build_registry(root)]


def format_registry(entries: Sequence[RegistryEntry]) -> str:
    """Render registry entries as a human-readable table.

    One row per benchmark, columns: id, domain, status, version, tags,
    contributor, license. Sorted by id (callers pass already-sorted entries).
    A header row is always present so empty registries are still legible.
    """
    headers = ("id", "domain", "status", "version", "tags", "contributor", "license")
    rows: list[tuple[str, ...]] = [headers]
    for e in entries:
        rows.append(
            (
                e.id,
                e.domain,
                e.status,
                e.version,
                ",".join(e.tags),
                e.contributor,
                e.license,
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(len(headers))]
    lines = []
    for i, row in enumerate(rows):
        line = "  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row))
        lines.append(line)
        if i == 0:
            lines.append("  ".join("-" * w for w in widths))
    if not entries:
        lines.append("(no registered benchmarks discovered)")
    return "\n".join(lines)
