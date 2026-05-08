"""Org-baseline drift check.

Verifies that every file in the manifest is byte-identical between the
nwarila-platform/.github canonical and a consumer repository.
"""

from .check import CheckResult, ResultStatus, run_check
from .manifest import BaselineFile, BaselineManifest, load_manifest

__all__ = [
    "BaselineFile",
    "BaselineManifest",
    "CheckResult",
    "ResultStatus",
    "load_manifest",
    "run_check",
]
