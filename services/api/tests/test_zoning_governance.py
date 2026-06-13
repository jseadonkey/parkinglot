from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "check_zoning_governance.py"


def test_zoning_governance_script_passes_current_config() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert '"24510"' in proc.stdout


def test_zoning_governance_fails_when_priority_county_not_curated(tmp_path: Path) -> None:
    gov = yaml.safe_load((REPO_ROOT / "data/zoning/governance.yaml").read_text(encoding="utf-8"))
    gov["county_coverage"]["24510"]["status"] = "in_review"
    path = tmp_path / "governance.yaml"
    path.write_text(yaml.safe_dump(gov), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--governance", str(path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 1
    assert "priority county 24510 must be curated" in proc.stderr
