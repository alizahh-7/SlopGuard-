from datetime import datetime, timedelta, timezone

from core.models import Ecosystem, PackageInfo, PackageRef
from core.scorer import score_all, score_package
from core.signals import SignalContext


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def ref(name: str, ecosystem: Ecosystem = Ecosystem.PYPI, source: str = "requirements") -> PackageRef:
    return PackageRef(name=name, raw=name, ecosystem=ecosystem, source=source)


def test_phantom_bands_and_unknown() -> None:
    declared = score_package(ref("missing"), PackageInfo(name="missing", ecosystem="pypi", exists=False), SignalContext(NOW))
    inferred = score_package(ref("missing", source="import"), PackageInfo(name="missing", ecosystem="pypi", exists=False), SignalContext(NOW))
    unknown = score_package(ref("slow"), PackageInfo(name="slow", ecosystem="pypi", exists=None), SignalContext(NOW))
    assert (declared.risk, declared.verdict) == (100, "BLOCK")
    assert (inferred.risk, inferred.verdict) == (70, "RISKY")
    assert (unknown.risk, unknown.verdict, unknown.findings[0].signal) == (0, "UNKNOWN", "lookup_failed")


def test_points_cap_and_determinism() -> None:
    package_ref = ref("rare-package", Ecosystem.NPM)
    info = PackageInfo(
        name="rare-package", ecosystem="npm", exists=True, created_at=NOW - timedelta(days=1), downloads=1,
        repo_url=None, release_count=1, install_scripts=["install"],
    )
    ctx = SignalContext(NOW, npm_top=("well-known-package",))
    first = score_package(package_ref, info, ctx)
    second = score_package(package_ref, info, ctx)
    assert (first.risk, first.verdict) == (99, "RISKY")
    assert first == second


def test_well_established_package_is_ok_and_summary_uses_order() -> None:
    good_ref = ref("requests")
    good_info = PackageInfo(name="requests", ecosystem="pypi", exists=True, created_at=NOW - timedelta(days=365), downloads=1_000_000, repo_url="https://github.com/psf/requests", release_count=10)
    verdict = score_package(good_ref, good_info, SignalContext(NOW, ("requests",)))
    result = score_all([good_ref], {("pypi", "requests"): good_info}, NOW)
    assert (verdict.risk, verdict.verdict) == (0, "OK")
    assert result.summary.counts["OK"] == 1
    assert result.summary.worst_verdict == "OK"
