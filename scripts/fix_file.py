import argparse
import asyncio
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.extract import extract
from core.registry import fetch_many
from core.remediate import remediate
from core.scorer import score_all


def guess_kind(path):
    name = path.name.lower()
    if name == "package.json":
        return "package_json"
    if name.endswith(".txt") and "req" in name:
        return "requirements"
    return "text"


async def run(path, write):
    content = path.read_text(encoding="utf-8")
    kind = guess_kind(path)
    refs = extract(content, kind, path.name)
    infos = await fetch_many(refs)
    result = score_all(refs, infos)
    out = remediate(content, kind, result)
    print("Checked", len(refs), "dependencies; worst verdict:", result.summary.worst_verdict)
    for c in out["changes"]:
        extra = " -> " + c["replacement"] if c["replacement"] else ""
        review = "  [needs your review]" if c["needs_review"] else ""
        print("  " + c["action"].upper() + " " + c["package"] + extra + review + ": " + c["reason"])
    if out["diff"]:
        print()
        print(out["diff"])
    if write and out["fixed_content"] != content:
        backup = path.with_name(path.name + ".slopguard.bak")
        shutil.copyfile(path, backup)
        path.write_text(out["fixed_content"], encoding="utf-8")
        print("\nWrote fixed file. Backup:", backup)
    elif write:
        print("\nNothing to change.")


def main():
    parser = argparse.ArgumentParser(description="SlopGuard fix-it (suggestions, verify before installing)")
    parser.add_argument("file")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(Path(args.file), args.write))


if __name__ == "__main__":
    main()
