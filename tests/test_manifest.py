"""Manifest schema validation tests."""

from __future__ import annotations

import json
import pathlib

import pytest
from baseline.manifest import BaselineManifest, load_manifest
from pydantic import ValidationError


def _write(tmp_path: pathlib.Path, payload: dict) -> pathlib.Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_minimal_valid_manifest(tmp_path):
    m = BaselineManifest.model_validate(
        {"version": "1", "files": [{"source": "a.md", "target": "a.md"}]}
    )
    assert m.version == "1"
    assert len(m.files) == 1


def test_load_from_disk(tmp_path):
    p = _write(tmp_path, {"version": "1", "files": [{"source": "a.md", "target": "a.md"}]})
    m = load_manifest(p)
    assert m.files[0].target == "a.md"


def test_unknown_top_level_key_rejected():
    with pytest.raises(ValidationError):
        BaselineManifest.model_validate(
            {"version": "1", "files": [{"source": "a", "target": "a"}], "extra": "no"}
        )


def test_unknown_file_key_rejected():
    with pytest.raises(ValidationError):
        BaselineManifest.model_validate(
            {"version": "1", "files": [{"source": "a", "target": "a", "mode": "x"}]}
        )


def test_unsupported_version_rejected():
    with pytest.raises(ValidationError):
        BaselineManifest.model_validate({"version": "2", "files": [{"source": "a", "target": "a"}]})


def test_empty_files_list_rejected():
    with pytest.raises(ValidationError):
        BaselineManifest.model_validate({"version": "1", "files": []})


def test_path_traversal_rejected():
    with pytest.raises(ValidationError):
        BaselineManifest.model_validate(
            {"version": "1", "files": [{"source": "../escape.md", "target": "ok.md"}]}
        )


def test_absolute_path_rejected():
    with pytest.raises(ValidationError):
        BaselineManifest.model_validate(
            {"version": "1", "files": [{"source": "/etc/passwd", "target": "ok.md"}]}
        )


def test_duplicate_targets_rejected():
    with pytest.raises(ValidationError):
        BaselineManifest.model_validate(
            {
                "version": "1",
                "files": [
                    {"source": "a.md", "target": "x.md"},
                    {"source": "b.md", "target": "x.md"},
                ],
            }
        )


def test_empty_path_rejected():
    with pytest.raises(ValidationError):
        BaselineManifest.model_validate(
            {"version": "1", "files": [{"source": "", "target": "ok.md"}]}
        )
