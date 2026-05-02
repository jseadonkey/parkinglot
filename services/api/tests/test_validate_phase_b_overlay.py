"""CLI validate_phase_b_overlay exits 0 on bundled sample GeoJSON."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "validate_phase_b_overlay.py"
SAMPLE = REPO_ROOT / "data" / "sample_parcels.geojson"


def test_validate_phase_b_overlay_sample_exits_zero() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    assert SAMPLE.is_file(), f"missing {SAMPLE}"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(SAMPLE)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        env=os.environ,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout

