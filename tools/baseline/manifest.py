"""Manifest schema + loader.

The manifest enumerates every file the consumer must mirror byte-identically
from the canonical org repo. Validated via pydantic so malformed manifests
fail loudly on load instead of silently mis-comparing.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BaselineFile(BaseModel):
    """One enforced file mapping."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        ...,
        description="Path within nwarila-platform/.github (the canonical).",
    )
    target: str = Field(
        ...,
        description="Path within the consumer repository.",
    )

    @field_validator("source", "target")
    @classmethod
    def _no_traversal(cls, v: str) -> str:
        # Reject path traversal — manifest paths must be repo-rooted.
        if v.startswith("/") or ".." in Path(v).parts:
            raise ValueError(f"path must be repo-rooted and contain no traversal: {v!r}")
        if not v:
            raise ValueError("path must be non-empty")
        return v


class BaselineManifest(BaseModel):
    """The full manifest."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(..., description='Manifest schema version. Currently "1".')
    files: list[BaselineFile] = Field(..., min_length=1)

    @field_validator("version")
    @classmethod
    def _supported_version(cls, v: str) -> str:
        if v != "1":
            raise ValueError(f"unsupported manifest version {v!r}; expected '1'")
        return v

    @field_validator("files")
    @classmethod
    def _unique_targets(cls, v: list[BaselineFile]) -> list[BaselineFile]:
        targets = [f.target for f in v]
        if len(set(targets)) != len(targets):
            raise ValueError("manifest contains duplicate target paths")
        return v


def load_manifest(path: Path | str) -> BaselineManifest:
    """Load + validate a manifest from disk. Raises on malformed input."""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    return BaselineManifest.model_validate(raw)
