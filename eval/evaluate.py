"""Evaluate deterministic SlopGuard scores against an intentionally small labelled corpus."""

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.models import Ecosystem, PackageInfo, PackageRef
from core.registry import fetch_many
from core.scorer import score_all


ROOT = Path(__file__).resolve().parent
RANK = {"OK": 0, "UNKNOWN": 1, "REVIEW": 2, "RISKY": 3, "BLOCK": 4}
OPERATING_POINTS = {"review": "REVIEW", "risky": "RISKY"}


def _ref(item: dict[str, str]) -> PackageRef:
    return PackageRef(name=item["name"], raw=item["name"], ecosystem=Ecosystem(item["ecosystem"]), source="requirements")


def _metrics(rows: list[dict[str, Any]], threshold: str) -> dict[str, Any]:
    flagged = lambda row: RANK[row["verdict"]] >= RANK[threshold]
    tp = sum(row["label"] == "risky" and flagged(row) for row in rows)
    fp = sum(row["label"] == "safe" and flagged(row) for row in rows)
    tn = sum(row["label"] == "safe" and not flagged(row) for row in rows)
    fn = sum(row["label"] == "risky" and not flagged(row) for row in rows)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"threshold": threshold, "tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0, "accuracy": (tp + tn) / len(rows) if rows else 0.0, "confusion_matrix": {"actual_risky": {"flagged": tp, "not_flagged": fn}, "actual_safe": {"flagged": fp, "not_flagged": tn}}}


def evaluate_items(items: list[dict[str, str]], infos: dict[tuple[str, str], PackageInfo]) -> dict[str, Any]:
    refs = [_ref(item) for item in items]
    scores = score_all(refs, infos).packages
    included, unknown, conflicts = [], [], []
    for item, score in zip(items, scores):
        row = {**item, "exists": score.info.exists, "verdict": score.verdict, "risk": score.risk, "findings": [finding.model_dump() for finding in score.findings]}
        if score.info.exists is None:
            unknown.append(row)
        elif item["category"] == "risky-phantom" and score.info.exists is True:
            conflicts.append(row)
        else:
            included.append(row)
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in included:
        by_category[row["category"]].append(row)
    return {"total_items": len(items), "included": len(included), "unknown_excluded": unknown, "label_conflicts": conflicts, "operating_points": {name: _metrics(included, threshold) for name, threshold in OPERATING_POINTS.items()}, "per_category": {category: {name: _metrics(rows, threshold) for name, threshold in OPERATING_POINTS.items()} for category, rows in sorted(by_category.items())}, "rows": included}


def _pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def _metric_table(metrics: dict[str, Any]) -> str:
    return "| TP | FP | TN | FN | Precision | Recall | F1 | Accuracy |\n| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n" + f"| {metrics['tp']} | {metrics['fp']} | {metrics['tn']} | {metrics['fn']} | {_pct(metrics['precision'])} | {_pct(metrics['recall'])} | {_pct(metrics['f1'])} | {_pct(metrics['accuracy'])} |"


def render_report(result: dict[str, Any]) -> str:
    lines = ["# SlopGuard scorer evaluation", "", "## Methodology", "", "This evaluates the deterministic scorer against a small author-labelled corpus. Registry results are fetched read-only and cached by core. `UNKNOWN` registry outcomes are excluded; an alleged phantom that exists is a label conflict and is excluded.", ""]
    for name, metrics in result["operating_points"].items():
        lines += [f"## Operating point: verdict ≥ {metrics['threshold']}", "", _metric_table(metrics), "", "Confusion matrix: actual risky → flagged/not flagged = " + f"{metrics['tp']}/{metrics['fn']}; actual safe → flagged/not flagged = {metrics['fp']}/{metrics['tn']}", ""]
    lines += ["## Per-category breakdown", "", "| Category | Included | Review F1 | Risky F1 |", "| --- | ---: | ---: | ---: |"]
    for category, points in result["per_category"].items():
        count = sum(points["review"][key] for key in ("tp", "fp", "tn", "fn"))
        lines.append(f"| {category} | {count} | {_pct(points['review']['f1'])} | {_pct(points['risky']['f1'])} |")
    lines += ["", "## Errors", ""]
    for name, metrics in result["operating_points"].items():
        threshold = metrics["threshold"]
        lines += [f"### Verdict ≥ {threshold}", ""]
        errors = [row for row in result["rows"] if (row["label"] == "safe" and RANK[row["verdict"]] >= RANK[threshold]) or (row["label"] == "risky" and RANK[row["verdict"]] < RANK[threshold])]
        if not errors:
            lines.append("No false positives or false negatives.")
        for row in errors:
            kind = "false positive" if row["label"] == "safe" else "false negative"
            findings = "; ".join(f"{finding['signal']}: {finding['message']}" for finding in row["findings"]) or "no findings"
            lines.append(f"- **{kind}** `{row['name']}` ({row['category']}; {row['verdict']}): {findings}")
        lines.append("")
    lines += ["## Exclusions and label conflicts", "", f"Unknown registry outcomes excluded: {len(result['unknown_excluded'])}.", f"Phantom label conflicts excluded: {len(result['label_conflicts'])}.", "", "## Limitations", "", "This is a small author-labelled set, not an independent ground truth. Popularity-based signals can penalise legitimate new or small packages. The npm top list is curated rather than a comprehensive popularity source. This is not a malware detector.", ""]
    return "\n".join(lines)


async def run_evaluation(root: Path = ROOT) -> dict[str, Any]:
    items = json.loads((root / "labeled.json").read_text(encoding="utf-8"))
    refs = [_ref(item) for item in items]
    infos = await fetch_many(refs)
    result = evaluate_items(items, infos)
    (root / "results.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (root / "report.md").write_text(render_report(result), encoding="utf-8")
    return result


def main() -> None:
    result = asyncio.run(run_evaluation())
    print(f"evaluated={result['included']} unknown_excluded={len(result['unknown_excluded'])} label_conflicts={len(result['label_conflicts'])}")


if __name__ == "__main__":
    main()
