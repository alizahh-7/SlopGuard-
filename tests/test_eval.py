import asyncio
import json
from pathlib import Path

from core.models import Ecosystem, PackageInfo
from eval import evaluate


def info(name: str, ecosystem: str, *, exists: bool | None = True, risky: bool = False) -> PackageInfo:
    return PackageInfo(name=name, ecosystem=Ecosystem(ecosystem), exists=exists, release_count=1 if risky else 10, downloads=1 if risky else 1_000_000, downloads_period="month" if ecosystem == "pypi" else "week", repo_url=None if risky else "https://example.com/source")


def test_metric_computation_has_known_confusion_matrix() -> None:
    items = [
        {"name": "safe-good", "ecosystem": "pypi", "label": "safe", "category": "safe-niche", "note": ""},
        {"name": "safe-flagged", "ecosystem": "pypi", "label": "safe", "category": "safe-niche", "note": ""},
        {"name": "missing", "ecosystem": "pypi", "label": "risky", "category": "risky-phantom", "note": ""},
        {"name": "risky-missed", "ecosystem": "pypi", "label": "risky", "category": "risky-lookalike", "note": ""},
    ]
    infos = {("pypi", "safe-good"): info("safe-good", "pypi"), ("pypi", "safe-flagged"): info("safe-flagged", "pypi", risky=True), ("pypi", "missing"): info("missing", "pypi", exists=False), ("pypi", "risky-missed"): info("risky-missed", "pypi")}
    result = evaluate.evaluate_items(items, infos)
    metrics = result["operating_points"]["review"]
    assert (metrics["tp"], metrics["fp"], metrics["tn"], metrics["fn"]) == (1, 1, 1, 1)
    assert metrics["precision"] == metrics["recall"] == metrics["f1"] == metrics["accuracy"] == 0.5


def test_unknown_and_phantom_label_conflict_are_excluded() -> None:
    items = [
        {"name": "unknown", "ecosystem": "pypi", "label": "safe", "category": "safe-niche", "note": ""},
        {"name": "real-phantom-label", "ecosystem": "pypi", "label": "risky", "category": "risky-phantom", "note": ""},
    ]
    infos = {("pypi", "unknown"): info("unknown", "pypi", exists=None), ("pypi", "real-phantom-label"): info("real-phantom-label", "pypi")}
    result = evaluate.evaluate_items(items, infos)
    assert result["included"] == 0
    assert len(result["unknown_excluded"]) == 1
    assert len(result["label_conflicts"]) == 1


def test_report_is_generated_with_mocked_registry(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "eval"
    root.mkdir()
    items = [{"name": "known", "ecosystem": "pypi", "label": "safe", "category": "safe-niche", "note": ""}]
    (root / "labeled.json").write_text(json.dumps(items), encoding="utf-8")

    async def fake_fetch(refs):
        return {("pypi", "known"): info("known", "pypi")}

    monkeypatch.setattr(evaluate, "fetch_many", fake_fetch)
    asyncio.run(evaluate.run_evaluation(root))
    report = (root / "report.md").read_text(encoding="utf-8")
    assert "Operating point: verdict ≥ REVIEW" in report
    assert "## Limitations" in report
    assert (root / "results.json").exists()
