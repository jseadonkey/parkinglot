"""Local pytest hooks — ensure zoning rules YAML resolves outside Docker."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_RULES = _REPO_ROOT / "data/zoning/wa/kent_king_surface_parking_rules.yaml"
if _DEFAULT_RULES.is_file():
    os.environ.setdefault("ZONING_RULES_PATH", str(_DEFAULT_RULES))
