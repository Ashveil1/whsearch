import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_versions_are_synchronized() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    python_version = pyproject["project"]["version"]
    npm = json.loads((ROOT / "npm" / "package.json").read_text(encoding="utf-8"))
    launcher = (ROOT / "npm" / "launcher.js").read_text(encoding="utf-8")
    match = re.search(r'BACKEND_VERSION = "([^"]+)"', launcher)
    assert match is not None, "BACKEND_VERSION missing from launcher.js"
    assert npm["version"] == python_version, (npm["version"], python_version)
    assert match.group(1) == python_version, (match.group(1), python_version)
