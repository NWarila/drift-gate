"""Manifest schema validation tests."""

from __future__ import annotations

import json
import pathlib

import pytest
from baseline.manifest import (
    BaselineManifest,
    ManifestError,
    _validate_manifest_dict,
    load_manifest,
)


def _write(tmp_path: pathlib.Path, payload: dict) -> pathlib.Path:
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_minimal_valid_manifest():
    m = _validate_manifest_dict({"version": "1", "files": [{"source": "a.md", "target": "a.md"}]})
    assert isinstance(m, BaselineManifest)
    assert m.version == "1"
    assert len(m.files) == 1
    assert m.files[0].source == "a.md"
    assert m.files[0].target == "a.md"


def test_load_from_disk(tmp_path):
    p = _write(tmp_path, {"version": "1", "files": [{"source": "a.md", "target": "a.md"}]})
    m = load_manifest(p)
    assert m.files[0].target == "a.md"


def test_load_invalid_json_raises_manifest_error(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid JSON"):
        load_manifest(p)


def test_unknown_top_level_key_rejected():
    with pytest.raises(ManifestError, match="unknown top-level key"):
        _validate_manifest_dict(
            {"version": "1", "files": [{"source": "a", "target": "a"}], "extra": "no"}
        )


def test_missing_top_level_key_rejected():
    with pytest.raises(ManifestError, match="missing required key"):
        _validate_manifest_dict({"version": "1"})


def test_unknown_file_key_rejected():
    with pytest.raises(ManifestError, match="unknown key"):
        _validate_manifest_dict(
            {"version": "1", "files": [{"source": "a", "target": "a", "mode": "x"}]}
        )


def test_unsupported_version_rejected():
    with pytest.raises(ManifestError, match="unsupported manifest version"):
        _validate_manifest_dict({"version": "2", "files": [{"source": "a", "target": "a"}]})


def test_non_string_version_rejected():
    with pytest.raises(ManifestError, match="must be a string"):
        _validate_manifest_dict({"version": 1, "files": [{"source": "a", "target": "a"}]})


def test_empty_files_list_rejected():
    with pytest.raises(ManifestError, match="at least one entry"):
        _validate_manifest_dict({"version": "1", "files": []})


def test_path_traversal_rejected():
    with pytest.raises(ManifestError, match=r"\.\."):
        _validate_manifest_dict(
            {"version": "1", "files": [{"source": "../escape.md", "target": "ok.md"}]}
        )


def test_absolute_path_rejected():
    with pytest.raises(ManifestError, match="repo-rooted"):
        _validate_manifest_dict(
            {"version": "1", "files": [{"source": "/etc/passwd", "target": "ok.md"}]}
        )


def test_duplicate_targets_rejected():
    with pytest.raises(ManifestError, match="duplicate target"):
        _validate_manifest_dict(
            {
                "version": "1",
                "files": [
                    {"source": "a.md", "target": "x.md"},
                    {"source": "b.md", "target": "x.md"},
                ],
            }
        )


def test_empty_path_rejected():
    with pytest.raises(ManifestError, match="non-empty"):
        _validate_manifest_dict({"version": "1", "files": [{"source": "", "target": "ok.md"}]})


def test_non_string_path_rejected():
    with pytest.raises(ManifestError, match="must be a string"):
        _validate_manifest_dict({"version": "1", "files": [{"source": 123, "target": "ok.md"}]})


def test_files_must_be_a_list():
    with pytest.raises(ManifestError, match="must be a list"):
        _validate_manifest_dict({"version": "1", "files": "not a list"})


def test_root_must_be_an_object():
    with pytest.raises(ManifestError, match="must be an object"):
        _validate_manifest_dict([{"version": "1"}])


def test_manifest_error_is_value_error_for_back_compat():
    """Subclasses ValueError so existing except-blocks keep working."""
    with pytest.raises(ValueError):
        _validate_manifest_dict({"version": "2", "files": [{"source": "a", "target": "a"}]})
