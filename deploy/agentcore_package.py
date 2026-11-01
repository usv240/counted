"""Build the AgentCore Runtime direct-deploy package: arm64 wheels plus the counted package, zipped for Linux.

    uv run python deploy/agentcore_package.py      -> build/agentcore/counted_agentcore.zip

AgentCore Runtime runs Python on arm64, so dependencies are resolved for aarch64-manylinux2014 with binary wheels
only. Only what the interview and assessment path imports is included (no web server, no MCP/A2A, no evals).
Permissions are set explicitly (644 files, 755 directories) because a zip built on Windows carries none.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "agentcore"
PKG = BUILD / "package"
OUT = BUILD / "counted_agentcore.zip"
PYTHON = "3.12"
REQUIREMENTS = ["strands-agents==1.63.0", "bedrock-agentcore==1.25.2", "cedarpy==4.12.2", "boto3==1.43.123",
                "httpx==0.28.1", "pydantic==2.14.2"]
SKIP = {"service", "__pycache__"}  # the web service (FastAPI, MCP, A2A) runs on ECS, not here

MAIN = '''"""AgentCore Runtime entry point for Counted."""
from counted.agentcore_app import app

if __name__ == "__main__":
    app.run()
'''


def main() -> None:
    shutil.rmtree(BUILD, ignore_errors=True)
    PKG.mkdir(parents=True)
    subprocess.run(["uv", "pip", "install", "--python-platform", "aarch64-manylinux2014", "--python-version", PYTHON,
                    "--target", str(PKG), "--only-binary=:all:", "--quiet", *REQUIREMENTS], check=True)
    src = ROOT / "src" / "counted"
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if path.is_file() and not (set(rel.parts) & SKIP):
            dest = PKG / "counted" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    (PKG / "main.py").write_text(MAIN, encoding="utf-8")

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(PKG.rglob("*")):
            rel = path.relative_to(PKG).as_posix()
            if "__pycache__" in rel:
                continue
            info = zipfile.ZipInfo(rel + ("/" if path.is_dir() else ""), date_time=(2026, 11, 1, 0, 0, 0))
            info.external_attr = ((0o40755 if path.is_dir() else 0o100644) << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, b"" if path.is_dir() else path.read_bytes())
    unzipped = sum(p.stat().st_size for p in PKG.rglob("*") if p.is_file())
    print(f"{OUT}: {OUT.stat().st_size / 1e6:.1f} MB zipped, {unzipped / 1e6:.1f} MB unzipped")


if __name__ == "__main__":
    main()
