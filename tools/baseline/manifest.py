"""Manifest schema + loader.

The manifest enumerates every file the consumer must mirror byte-identically
from the canonical source repo. Validated with stdlib-only checks so a
malformed manifest fails loudly on load instead of silently mis-comparing.

Schema (v1)
-----------
{
  "version": "1",
  "files": [
    {"source": "<repo-rooted relative path>", "target": "<repo-rooted relative path>"},
    ...
  ]
}

- Top-level keys: exactly {"version", "files"} (extra keys forbidden).
- "version": string equal to "1".
- "files": non-empty list.
- Per file: keys exactly {"source", "target"}; both non-empty strings;
  neither absolute; neither contains a ".." component.
- "target" values are unique across the manifest.

Schema (v2)
-----------
{
  "version": "2",
  "byte_identical": [
    {"source": "<repo-rooted relative path>", "target": "<repo-rooted relative path>"},
    ...
  ],
  "scaffold_starter": [
    {"source": "<repo-rooted relative path>", "target": "<repo-rooted relative path>"},
    ...
  ]
}

Only byte_identical entries are enforced by drift-gate. scaffold_starter entries
are validated as documented source paths but are intentionally not compared; they
exist for template starter files derivative repositories are expected to rewrite.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_V1_SCHEMA_VERSION = "1"
_V2_SCHEMA_VERSION = "2"
_V1_TOP_LEVEL_KEYS = frozenset({"version", "files"})
_V2_TOP_LEVEL_KEYS = frozenset({"version", "byte_identical", "scaffold_starter"})
_FILE_KEYS = frozenset({"source", "target"})


class ManifestError(ValueError):
    """Raised when a manifest fails schema validation.

    Inherits from ValueError so existing callers that catch ValueError
    keep working; subclassing also lets tests assert on the exact type.
    """


@dataclass(frozen=True)
class BaselineFile:
    """One enforced file mapping."""

    source: str
    target: str


@dataclass(frozen=True)
class BaselineManifest:
    """The full manifest."""

    version: str
    files: list[BaselineFile]
    scaffold_starter: list[BaselineFile] | None = None


def _validate_path(field: str, value: Any) -> str:
    """Validate a single source/target path string. Returns the validated value."""
    if not isinstance(value, str):
        raise ManifestError(f"{field!r} must be a string, got {type(value).__name__}")
    if not value:
        raise ManifestError(f"{field!r} must be non-empty")
    if value.startswith("/"):
        raise ManifestError(f"{field!r} must be repo-rooted (no leading '/'): {value!r}")
    if ".." in Path(value).parts:
        raise ManifestError(f"{field!r} must not contain '..' components: {value!r}")
    return value


def _validate_manifest_dict(raw: Any) -> BaselineManifest:
    """Validate a parsed JSON object as a BaselineManifest."""
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest root must be an object, got {type(raw).__name__}")
    if "version" not in raw:
        raise ManifestError("manifest missing required key(s) ['version']")

    version = raw["version"]
    if not isinstance(version, str):
        raise ManifestError(f"'version' must be a string, got {type(version).__name__}")
    if version == _V1_SCHEMA_VERSION:
        return _validate_v1_manifest(raw, version)
    if version == _V2_SCHEMA_VERSION:
        return _validate_v2_manifest(raw, version)
    raise ManifestError(
        f"unsupported manifest version {version!r}; expected "
        f"{_V1_SCHEMA_VERSION!r} or {_V2_SCHEMA_VERSION!r}"
    )


def _validate_top_level_keys(raw: dict[str, Any], allowed: frozenset[str]) -> None:
    keys = set(raw.keys())
    extra = keys - allowed
    if extra:
        raise ManifestError(
            f"manifest has unknown top-level key(s) {sorted(extra)!r}; "
            f"allowed keys: {sorted(allowed)!r}"
        )
    missing = allowed - keys
    if missing:
        raise ManifestError(f"manifest missing required key(s) {sorted(missing)!r}")


def _validate_file_group(field: str, raw: Any, *, allow_empty: bool) -> list[BaselineFile]:
    if not isinstance(raw, list):
        raise ManifestError(f"{field!r} must be a list, got {type(raw).__name__}")
    if not raw and not allow_empty:
        raise ManifestError(f"{field!r} must contain at least one entry")
    return [_validate_file(i, entry, field=field) for i, entry in enumerate(raw)]


def _validate_file(idx: int, raw: Any, *, field: str = "files") -> BaselineFile:
    """Validate one file entry from the manifest. idx is 0-based position."""
    if not isinstance(raw, dict):
        raise ManifestError(f"{field}[{idx}] must be an object, got {type(raw).__name__}")
    keys = set(raw.keys())
    extra = keys - _FILE_KEYS
    if extra:
        raise ManifestError(
            f"{field}[{idx}] has unknown key(s) {sorted(extra)!r}; "
            f"allowed keys: {sorted(_FILE_KEYS)!r}"
        )
    missing = _FILE_KEYS - keys
    if missing:
        raise ManifestError(f"{field}[{idx}] missing required key(s) {sorted(missing)!r}")
    return BaselineFile(
        source=_validate_path(f"{field}[{idx}].source", raw["source"]),
        target=_validate_path(f"{field}[{idx}].target", raw["target"]),
    )


def _reject_duplicate_targets(files: list[BaselineFile], *, field: str) -> None:
    targets = [f.target for f in files]
    if len(set(targets)) == len(targets):
        return
    seen: set[str] = set()
    dups: list[str] = []
    for t in targets:
        if t in seen and t not in dups:
            dups.append(t)
        seen.add(t)
    raise ManifestError(f"{field} contains duplicate target paths: {dups!r}")


def _validate_v1_manifest(raw: dict[str, Any], version: str) -> BaselineManifest:
    _validate_top_level_keys(raw, _V1_TOP_LEVEL_KEYS)
    files_raw = raw["files"]
    files = _validate_file_group("files", files_raw, allow_empty=False)
    _reject_duplicate_targets(files, field="manifest")
    return BaselineManifest(version=version, files=files)


def _validate_v2_manifest(raw: dict[str, Any], version: str) -> BaselineManifest:
    _validate_top_level_keys(raw, _V2_TOP_LEVEL_KEYS)
    byte_identical = _validate_file_group(
        "byte_identical", raw["byte_identical"], allow_empty=False
    )
    scaffold_starter = _validate_file_group(
        "scaffold_starter", raw["scaffold_starter"], allow_empty=True
    )
    _reject_duplicate_targets(byte_identical + scaffold_starter, field="manifest")
    return BaselineManifest(
        version=version,
        files=byte_identical,
        scaffold_starter=scaffold_starter,
    )


def load_manifest(path: Path | str) -> BaselineManifest:
    """Load + validate a manifest from disk. Raises ManifestError on malformed input."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifest at {p} is not valid JSON: {e}") from e
    return _validate_manifest_dict(raw)
