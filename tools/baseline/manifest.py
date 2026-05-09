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
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = "1"
_TOP_LEVEL_KEYS = frozenset({"version", "files"})
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


def _validate_file(idx: int, raw: Any) -> BaselineFile:
    """Validate one file entry from the manifest. idx is 0-based position."""
    if not isinstance(raw, dict):
        raise ManifestError(f"files[{idx}] must be an object, got {type(raw).__name__}")
    keys = set(raw.keys())
    extra = keys - _FILE_KEYS
    if extra:
        raise ManifestError(
            f"files[{idx}] has unknown key(s) {sorted(extra)!r}; "
            f"allowed keys: {sorted(_FILE_KEYS)!r}"
        )
    missing = _FILE_KEYS - keys
    if missing:
        raise ManifestError(f"files[{idx}] missing required key(s) {sorted(missing)!r}")
    return BaselineFile(
        source=_validate_path(f"files[{idx}].source", raw["source"]),
        target=_validate_path(f"files[{idx}].target", raw["target"]),
    )


def _validate_manifest_dict(raw: Any) -> BaselineManifest:
    """Validate a parsed JSON object as a BaselineManifest."""
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest root must be an object, got {type(raw).__name__}")
    keys = set(raw.keys())
    extra = keys - _TOP_LEVEL_KEYS
    if extra:
        raise ManifestError(
            f"manifest has unknown top-level key(s) {sorted(extra)!r}; "
            f"allowed keys: {sorted(_TOP_LEVEL_KEYS)!r}"
        )
    missing = _TOP_LEVEL_KEYS - keys
    if missing:
        raise ManifestError(f"manifest missing required key(s) {sorted(missing)!r}")

    version = raw["version"]
    if not isinstance(version, str):
        raise ManifestError(f"'version' must be a string, got {type(version).__name__}")
    if version != _SCHEMA_VERSION:
        raise ManifestError(
            f"unsupported manifest version {version!r}; expected {_SCHEMA_VERSION!r}"
        )

    files_raw = raw["files"]
    if not isinstance(files_raw, list):
        raise ManifestError(f"'files' must be a list, got {type(files_raw).__name__}")
    if len(files_raw) < 1:
        raise ManifestError("'files' must contain at least one entry")

    files = [_validate_file(i, entry) for i, entry in enumerate(files_raw)]

    targets = [f.target for f in files]
    if len(set(targets)) != len(targets):
        seen: set[str] = set()
        dups: list[str] = []
        for t in targets:
            if t in seen and t not in dups:
                dups.append(t)
            seen.add(t)
        raise ManifestError(f"manifest contains duplicate target paths: {dups!r}")

    return BaselineManifest(version=version, files=files)


def load_manifest(path: Path | str) -> BaselineManifest:
    """Load + validate a manifest from disk. Raises ManifestError on malformed input."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ManifestError(f"manifest at {p} is not valid JSON: {e}") from e
    return _validate_manifest_dict(raw)
