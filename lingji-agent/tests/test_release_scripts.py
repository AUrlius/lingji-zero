"""Release / CI / Chaos 脚本存在性与语法检查 — 四期 4.3 + 4.4"""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = [
    REPO_ROOT / "scripts" / "ci-integration.sh",
    REPO_ROOT / "scripts" / "compose-integration-smoke.sh",
    REPO_ROOT / "scripts" / "deploy-gateway.sh",
    REPO_ROOT / "scripts" / "chaos-spotcheck.sh",
]


class TestReleaseScripts:
    def test_scripts_exist(self):
        for path in SCRIPTS:
            assert path.is_file(), f"missing {path}"

    def test_scripts_bash_syntax(self):
        for path in SCRIPTS:
            result = subprocess.run(
                ["bash", "-n", str(path)],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stderr
