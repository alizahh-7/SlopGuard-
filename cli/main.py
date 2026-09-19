"""Command-line interface that delegates extraction, lookup, and scoring to core."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer

from core.extract import extract
from core.models import PackageRef, ScanResult
from core.registry import fetch_many
from core.scorer import score_all


app = typer.Typer(add_completion=False, no_args_is_help=True)
_KINDS = {"auto", "requirements", "package_json", "python", "javascript", "text"}
_THRESHOLDS = {"review": 25, "risky": 60, "block": 100, "never": 101}


def _kind_for_path(path: str, selected: Optional[str]) -> str:
    if selected:
        return selected
    name = Path(path).name.lower()
    if name == "package.json":
        return "package_json"
    if name.startswith("requirements") and name.endswith(".txt"):
        return "requirements"
    if name.endswith(".py"):
        return "python"
    if name.endswith((".js", ".jsx", ".ts", ".tsx")):
        return "javascript"
    return "auto"


def _merge_refs(refs: list[PackageRef]) -> list[PackageRef]:
    merged: dict[tuple[str, str], PackageRef] = {}
    for ref in refs:
        key = (ref.ecosystem.value, ref.name)
        prior = merged.get(key)
        if prior is None or (prior.confidence == "inferred" and ref.confidence == "declared"):
            merged[key] = ref
    return list(merged.values())


def _read_source(path: str) -> str:
    if path == "-":
        return typer.get_text_stream("stdin").read()
    return Path(path).read_text(encoding="utf-8")


def _reason(result) -> str:
    return result.findings[0].message if result.findings else "no risk signals"


def _badge(verdict: str) -> str:
    colors = {"OK": typer.colors.GREEN, "REVIEW": typer.colors.YELLOW, "RISKY": typer.colors.RED, "BLOCK": typer.colors.BRIGHT_RED, "UNKNOWN": typer.colors.MAGENTA}
    value = f"[{verdict}]"
    return typer.style(value, fg=colors[verdict], bold=True) if sys.stdout.isatty() else value


def _render_text(result: ScanResult) -> str:
    lines = [f"{_badge(item.verdict)} {item.ref.name} risk={item.risk} — {_reason(item)}" for item in result.packages]
    unknown = result.summary.counts.get("UNKNOWN", 0)
    if unknown:
        lines.append(f"{unknown} could not be verified")
    lines.append(f"Summary: {result.summary.total} packages; worst verdict {result.summary.worst_verdict}.")
    return "\n".join(lines)


def _render_markdown(result: ScanResult) -> str:
    lines = ["| Package | Verdict | Risk | Why |", "| --- | --- | ---: | --- |"]
    for item in result.packages:
        reason = _reason(item).replace("|", "\\|")
        lines.append(f"| {item.ref.name} | {item.verdict} | {item.risk} | {reason} |")
    unknown = result.summary.counts.get("UNKNOWN", 0)
    summary = f"Summary: {result.summary.total} packages; worst verdict {result.summary.worst_verdict}."
    if unknown:
        summary += f" **{unknown} could not be verified.**"
    lines.append(summary)
    return "\n".join(lines)


def _set_cache_disabled(disabled: bool) -> tuple[Optional[str], bool]:
    from core import registry

    old_env = os.environ.get("SLOPGUARD_NO_CACHE")
    old_disabled = registry._CACHE.disabled
    if disabled:
        os.environ["SLOPGUARD_NO_CACHE"] = "1"
        registry._CACHE.disabled = True
    return old_env, old_disabled


def _restore_cache(old_env: Optional[str], old_disabled: bool) -> None:
    from core import registry

    if old_env is None:
        os.environ.pop("SLOPGUARD_NO_CACHE", None)
    else:
        os.environ["SLOPGUARD_NO_CACHE"] = old_env
    registry._CACHE.disabled = old_disabled


@app.command()
def scan(
    paths: list[str] = typer.Argument(..., metavar="PATH..."),
    fail_on: str = typer.Option("risky", "--fail-on"),
    output_format: str = typer.Option("text", "--format"),
    kind: Optional[str] = typer.Option(None, "--kind"),
    no_cache: bool = typer.Option(False, "--no-cache"),
) -> None:
    """Scan dependency files or standard input without executing their contents."""
    if fail_on not in _THRESHOLDS or output_format not in {"text", "json", "md"} or (kind and kind not in _KINDS):
        typer.echo("Error: invalid option value", err=True)
        raise typer.Exit(2)
    try:
        refs: list[PackageRef] = []
        for path in paths:
            content = _read_source(path)
            refs.extend(extract(content, _kind_for_path(path, kind), None if path == "-" else path))
    except (OSError, UnicodeError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2) from exc
    refs = _merge_refs(refs)
    truncated = len(refs) > 200
    refs = refs[:200]
    old_env, old_disabled = _set_cache_disabled(no_cache)
    try:
        infos = asyncio.run(fetch_many(refs))
    except (OSError, RuntimeError) as exc:
        typer.echo(f"Error: registry lookup failed: {exc}", err=True)
        raise typer.Exit(2) from exc
    finally:
        _restore_cache(old_env, old_disabled)
    result = score_all(refs, infos)
    result.summary.truncated = truncated
    if output_format == "json":
        typer.echo(result.model_dump_json())
    elif output_format == "md":
        typer.echo(_render_markdown(result))
    else:
        typer.echo(_render_text(result))
    if any(item.verdict != "UNKNOWN" and item.risk >= _THRESHOLDS[fail_on] for item in result.packages):
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Print the SlopGuard version."""
    typer.echo("slopguard 0.1.0")


if __name__ == "__main__":
    app()
