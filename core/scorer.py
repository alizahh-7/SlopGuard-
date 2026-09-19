"""Deterministic risk aggregation for package metadata."""

from datetime import datetime, timezone

from .models import PackageInfo, PackageRef, PackageVerdict, ScanResult, ScanSummary
from .signals import SIGNALS, SignalContext, default_context, nearest_top_name


def score_package(ref: PackageRef, info: PackageInfo, ctx: SignalContext | None = None) -> PackageVerdict:
    ctx = ctx or default_context()
    if info.exists is None:
        findings = [finding for finding in (signal(ref, info, ctx) for signal in SIGNALS) if finding and finding.signal == "lookup_failed"]
        return PackageVerdict(ref=ref, info=info, risk=0, verdict="UNKNOWN", findings=findings)
    findings = [finding for signal in SIGNALS if (finding := signal(ref, info, ctx)) is not None]
    declared_phantom = info.exists is False and ref.confidence == "declared"
    malicious = info.osv_malicious
    risk = 100 if declared_phantom or malicious else min(99, sum(finding.points for finding in findings))
    verdict = "BLOCK" if risk == 100 else "RISKY" if risk >= 60 else "REVIEW" if risk >= 25 else "OK"
    signals = {finding.signal for finding in findings}
    alternative = nearest_top_name(ref, ctx) if signals & {"typosquat", "lookalike_affix", "phantom"} else None
    return PackageVerdict(ref=ref, info=info, risk=risk, verdict=verdict, findings=findings, alternative=alternative)


def score_all(refs: list[PackageRef], infos: dict[tuple[str, str], PackageInfo], now: datetime | None = None) -> ScanResult:
    scanned_at = now or datetime.now(timezone.utc)
    ctx = default_context(scanned_at)
    packages = [score_package(ref, infos.get((ref.ecosystem.value, ref.name), PackageInfo(name=ref.name, ecosystem=ref.ecosystem)), ctx) for ref in refs]
    order = {"OK": 0, "UNKNOWN": 1, "REVIEW": 2, "RISKY": 3, "BLOCK": 4}
    counts = {verdict: 0 for verdict in order}
    for package in packages:
        counts[package.verdict] += 1
    worst = max((package.verdict for package in packages), key=order.__getitem__, default="OK")
    return ScanResult(packages=packages, summary=ScanSummary(counts=counts, worst_verdict=worst, total=len(packages)), scanned_at=scanned_at)
