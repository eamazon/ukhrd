"""Build ukhrd.mcpb — the MCP server as a one-click MCP Bundle for desktop AI apps.

    python scripts/build_bundle.py [folder]        (default: the current folder)

An MCP Bundle is a zip with a manifest.json that tells the app how to start the server. This one is the
"uv" kind: the app installs Python and the MCP library itself, then runs
`uv run --directory <bundle> src/server.py`. Nothing else needs installing.

The bundle carries the code, never the data. With no data/ beside it, the server downloads ukhrd.db from
the latest GitHub release and fetches a newer one once its copy is a day old (mcp_server.latest_copy).

The tool list is read from mcp_server.TOOLS, so the manifest cannot drift from what the server offers.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ukhrd import files, mcp_server  # noqa: E402

REPO = "https://github.com/eamazon/ukhrd"

SERVER = '''"""Start the UKHRD MCP server from inside the bundle: uv run --directory <bundle> src/server.py"""
from ukhrd.mcp_server import main

if __name__ == "__main__":
    main()
'''


def _summary(tool) -> str:
    return " ".join((tool.__doc__ or "").strip().split("\n\n")[0].split())


def manifest(version: str) -> dict:
    credit = " ".join(sorted({s["attribution"] for s in files.read(files.sources_path())}))
    return {
        "manifest_version": "0.4",
        "name": "ukhrd",
        "display_name": "UKHRD — UK Health Reference Data",
        "version": version,
        "description": "What the codes in NHS data mean: the NHS Commissioning Data Sets code lists, every "
                       "version kept, each with the NHS page it came from.",
        "long_description": (
            "Look up what a code in NHS data means today, what it meant on any past date, and every version "
            "of it. Holds the code lists used by the NHS Commissioning Data Sets, copied exactly as published "
            "in the NHS Data Model and Dictionary.\n\n"
            "Read-only. It downloads the newest data from the UKHRD GitHub releases and fetches a newer copy "
            "once a day. Nothing is sent anywhere.\n\n"
            f"**Where the data comes from.** {credit} UKHRD is independent and not endorsed by NHS England; "
            "the NHS Data Model and Dictionary is the authority."),
        "author": {"name": "UKHRD maintainers", "url": REPO},
        "repository": {"type": "git", "url": REPO + ".git"},
        "homepage": REPO,
        "documentation": REPO + "#for-ai-assistants-mcp",
        "support": REPO + "/issues",
        "server": {
            "type": "uv",
            "entry_point": "src/server.py",
            "mcp_config": {"command": "uv", "args": ["run", "--directory", "${__dirname}", "src/server.py"]},
        },
        "tools": [{"name": t.__name__, "description": _summary(t)} for t in mcp_server.TOOLS],
        "keywords": ["nhs", "health", "reference data", "codes", "data dictionary", "uk"],
        "license": "MIT",
        "compatibility": {"platforms": ["darwin", "win32", "linux"], "runtimes": {"python": ">=3.10"}},
    }


def build(folder: pathlib.Path) -> pathlib.Path:
    """Write ukhrd.mcpb into `folder` and return its path."""
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    pyproject = (f'[project]\nname = "ukhrd-bundle"\nversion = "{version}"\n'
                 'description = "UKHRD MCP server"\nrequires-python = ">=3.10"\ndependencies = ["mcp>=2.2,<3"]\n')
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "ukhrd.mcpb"
    code = sorted(p for p in (ROOT / "src" / "ukhrd").rglob("*.py") if "__pycache__" not in p.parts)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest(version), indent=2, ensure_ascii=False) + "\n")
        z.writestr("pyproject.toml", pyproject)
        z.write(ROOT / "LICENSE", "LICENSE")
        z.writestr("src/server.py", SERVER)
        for path in code:
            z.write(path, "src/" + path.relative_to(ROOT / "src").as_posix())
    return out


def main() -> int:
    out = build(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "."))
    print(f"✓  {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
