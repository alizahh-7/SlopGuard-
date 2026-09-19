"""Aggregate private benchmark records without publishing raw package names."""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def mask_name(name: str) -> str:
    return f"{name[:3]}***{len(name)}"


def build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_model[record["model"]].append(record)
    models: dict[str, dict[str, Any]] = {}
    all_phantoms: dict[tuple[str, str], set[str]] = defaultdict(set)
    repeat_counts: Counter[tuple[str, str]] = Counter()
    verdicts: Counter[str] = Counter()
    for model, rows in by_model.items():
        packages = [package for row in rows if row.get("ok") for package in row.get("packages", [])]
        phantoms = [package for package in packages if package.get("exists") is False]
        names = {(package["ecosystem"], package["name"]) for package in phantoms}
        for ecosystem, name in names:
            all_phantoms[(ecosystem, name)].add(model)
        grouped: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
        for row in rows:
            for package in row.get("packages", []):
                if package.get("exists") is False:
                    grouped[row["prompt_id"]][(package["ecosystem"], package["name"])] += 1
        recurring = {name for counts in grouped.values() for name, count in counts.items() if count >= 2}
        for package in packages:
            if package.get("exists") is True:
                verdicts[package["verdict"]] += 1
        models[model] = {
            "calls": len(rows), "ok_calls": sum(bool(row.get("ok")) for row in rows),
            "total_package_refs": len(packages), "unique_packages": len({(p["ecosystem"], p["name"]) for p in packages}),
            "phantom_refs": len(phantoms), "phantom_rate": len(phantoms) / len(packages) if packages else 0.0,
            "prompts_with_phantom_pct": 100 * len({row["prompt_id"] for row in rows if any(p.get("exists") is False for p in row.get("packages", []))}) / len({row["prompt_id"] for row in rows}) if rows else 0.0,
            "unique_phantoms": len(names),
            "recurring_same_prompt_model_share": len(recurring) / len(names) if names else 0.0,
        }
        for package in phantoms:
            repeat_counts[(package["ecosystem"], package["name"])] += 1
    phantom_names = set(all_phantoms)
    repeated = repeat_counts.most_common(15)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "run_counts": {model: len(rows) for model, rows in by_model.items()}, "models": models,
        "phantom_share_across_2_models": len({name for name, seen in all_phantoms.items() if len(seen) >= 2}) / len(phantom_names) if phantom_names else 0.0,
        "top_repeated_phantoms": [{"name": mask_name(name), "count": count} for (_, name), count in repeated],
        "phantom_share_still_unregistered": 1.0 if phantom_names else 0.0,
        "existing_package_verdict_distribution": dict(sorted(verdicts.items())),
        "methodology": "Prompts request dependency lists only; names are extracted, checked with public registries, and scored deterministically.",
        "limitations": "These are one-off samples at temperature 0.8, not a definitive measurement.",
    }


def write_results(records: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    private = root / "results" / "private"
    private.mkdir(parents=True, exist_ok=True)
    with (private / "raw.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    summary = build_summary(records)
    target = root / "results" / "summary.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
