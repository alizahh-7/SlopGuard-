from datetime import datetime, timedelta, timezone

import pytest

from core.models import Ecosystem, PackageInfo, PackageRef
from core.signals import SIGNALS, SignalContext


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_ref(name: str, ecosystem: Ecosystem = Ecosystem.PYPI, source: str = "requirements") -> PackageRef:
    return PackageRef(name=name, raw=name, ecosystem=ecosystem, source=source)


def make_info(name: str, ecosystem: Ecosystem = Ecosystem.PYPI, **values) -> PackageInfo:
    values.setdefault("exists", True)
    values.setdefault("repo_url", "https://example.test/source")
    return PackageInfo(name=name, ecosystem=ecosystem, **values)


def findings(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> dict[str, int]:
    return {finding.signal: finding.points for signal in SIGNALS if (finding := signal(ref, info, ctx))}


@pytest.mark.parametrize(
    ("ref", "info", "ctx", "expected"),
    [
        (make_ref("ghost"), make_info("ghost", exists=False), SignalContext(NOW), {"phantom": 100}),
        (make_ref("ghost", source="import"), make_info("ghost", exists=False), SignalContext(NOW), {"phantom": 70}),
        (make_ref("bad"), make_info("bad", osv_malicious=True), SignalContext(NOW), {"malicious_advisory": 100}),
        (make_ref("reqeusts"), make_info("reqeusts"), SignalContext(NOW, ("requests",)), {"typosquat": 40}),
        (make_ref("abc"), make_info("abc"), SignalContext(NOW, ("abd",)), {}),
        (make_ref("requests"), make_info("requests"), SignalContext(NOW, ("requests",)), {}),
        (make_ref("requests-python"), make_info("requests-python"), SignalContext(NOW, ("requests",)), {"lookalike_affix": 25}),
        (make_ref("new"), make_info("new", created_at=NOW - timedelta(days=29)), SignalContext(NOW), {"very_new": 35}),
        (make_ref("new"), make_info("new", created_at=NOW - timedelta(days=30)), SignalContext(NOW), {"very_new": 15}),
        (make_ref("new"), make_info("new", created_at=NOW - timedelta(days=89)), SignalContext(NOW), {"very_new": 15}),
        (make_ref("new"), make_info("new", created_at=NOW - timedelta(days=90)), SignalContext(NOW), {}),
        (make_ref("low"), make_info("low", downloads=499), SignalContext(NOW), {"low_downloads": 25}),
        (make_ref("low"), make_info("low", downloads=500), SignalContext(NOW), {"low_downloads": 10}),
        (make_ref("low"), make_info("low", downloads=5000), SignalContext(NOW), {}),
        (make_ref("low", Ecosystem.NPM), make_info("low", Ecosystem.NPM, downloads=99), SignalContext(NOW), {"low_downloads": 25}),
        (make_ref("low", Ecosystem.NPM), make_info("low", Ecosystem.NPM, downloads=100), SignalContext(NOW), {"low_downloads": 10}),
        (make_ref("low", Ecosystem.NPM), make_info("low", Ecosystem.NPM, downloads=1000), SignalContext(NOW), {}),
        (make_ref("hidden"), make_info("hidden", repo_url=None), SignalContext(NOW), {"no_repo": 15}),
        (make_ref("once"), make_info("once", release_count=1), SignalContext(NOW), {"single_release": 10}),
        (make_ref("script", Ecosystem.NPM), make_info("script", Ecosystem.NPM, install_scripts=["install"]), SignalContext(NOW), {"install_script": 20}),
        (make_ref("unknown"), PackageInfo(name="unknown", ecosystem="pypi", exists=None), SignalContext(NOW), {"lookup_failed": 0}),
    ],
)
def test_each_signal(ref, info, ctx, expected) -> None:
    assert findings(ref, info, ctx) == expected
