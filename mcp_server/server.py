"""SlopGuard MCP server. Lets AI coding agents verify packages BEFORE installing.
Read-only: it never installs anything. stdout is the protocol channel, so log to stderr only."""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

from mcp.server.fastmcp import FastMCP  # noqa: E402

from core.extract import extract  # noqa: E402
from core.registry import fetch_many  # noqa: E402
from core.scorer import score_all  # noqa: E402

MAX_PACKAGES = 30
mcp = FastMCP("slopguard")


def _val(x):
    return str(getattr(x, "value", x))


async def _check_text(text):
    refs = extract(text, "text")[:MAX_PACKAGES]
    if not refs:
        return {
            "safe_to_install": None,
            "packages": [],
            "instruction": "No package names found in that command. If it installs from a file "
            "(for example -r requirements.txt), scan the file contents with SlopGuard first.",
        }
    infos = await fetch_many(refs)
    result = score_all(refs, infos)
    rows = []
    for item in result.packages:
        reasons = [(f.beginner_message or f.message) for f in (item.findings or [])][:3]
        rows.append(
            {
                "name": item.ref.name,
                "ecosystem": _val(item.ref.ecosystem),
                "verdict": _val(item.verdict),
                "risk_score": item.risk,
                "reasons": reasons,
                "suggested_alternative": item.alternative,
            }
        )
    safe = all(r["verdict"] == "OK" for r in rows)
    if safe:
        instruction = "All packages passed the checks (no risk signals in public metadata). This is not a guarantee."
    else:
        instruction = (
            "Do NOT install packages marked BLOCK or RISKY. For REVIEW or UNKNOWN, stop and ask the user. "
            "If a suggested_alternative exists, propose it and ask the user to confirm."
        )
    return {"safe_to_install": safe, "packages": rows, "instruction": instruction}


@mcp.tool()
async def check_packages(packages: list[str], ecosystem: str = "pypi") -> dict:
    """Check package names for phantom, typosquatted or suspicious dependencies before installing.
    ecosystem is 'pypi' or 'npm'."""
    eco = ecosystem.strip().lower()
    if eco not in ("pypi", "npm"):
        return {"error": "ecosystem must be 'pypi' or 'npm'"}
    names = [p.strip() for p in packages if isinstance(p, str) and p.strip()][:MAX_PACKAGES]
    prefix = "pip install " if eco == "pypi" else "npm install "
    return await _check_text(prefix + " ".join(names))


@mcp.tool()
async def check_install_command(command: str) -> dict:
    """Check the packages in a pip/pip3/npm/yarn/pnpm install command BEFORE running it."""
    return await _check_text(command[:5000])


if __name__ == "__main__":
    mcp.run()
