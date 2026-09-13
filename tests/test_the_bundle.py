"""What the one-click bundle promises: every tool the server has, the credit, and no data or clutter."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import zipfile

_spec = importlib.util.spec_from_file_location(
    "build_bundle", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "build_bundle.py")
build_bundle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_bundle)   # puts src/ on the path, so it must load before ukhrd is imported
mcp_server = build_bundle.mcp_server


def test_the_bundle_lists_every_tool_carries_the_credit_and_no_data(tmp_path):
    path = build_bundle.build(tmp_path)

    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        manifest = json.loads(z.read("manifest.json"))

    assert {t["name"] for t in manifest["tools"]} == {t.__name__ for t in mcp_server.TOOLS}
    assert all(t["description"] for t in manifest["tools"])
    assert manifest["server"]["type"] == "uv" and "src/server.py" in names
    assert "src/ukhrd/mcp_server.py" in names and "pyproject.toml" in names
    assert "Contains information from NHS England" in manifest["long_description"]
    assert "not endorsed" in manifest["long_description"]
    assert not [n for n in names if n.startswith("data/") or n.endswith((".db", ".pyc", ".csv"))
                or "__pycache__" in n], "the bundle carries code only; the server fetches the data"
