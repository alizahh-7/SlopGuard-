from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from core import Ecosystem, PackageInfo, PackageRef, PackageVerdict, ScanResult, ScanSummary


def test_models_construct_and_normalize() -> None:
    ref = PackageRef(
        name="Requests_Extra",
        raw="Requests_Extra",
        ecosystem=Ecosystem.PYPI,
        source="requirements",
    )
    info = PackageInfo(name=ref.name, ecosystem=ref.ecosystem, exists=True)
    verdict = PackageVerdict(ref=ref, info=info, risk=25, verdict="OK")

    assert ref.name == "requests-extra"
    assert ref.confidence == "declared"
    assert verdict.trust == 75


def test_json_round_trip() -> None:
    result = ScanResult(
        summary=ScanSummary(counts={"UNKNOWN": 1}, total=1),
        scanned_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert ScanResult.model_validate_json(result.model_dump_json()) == result


def test_trust_must_equal_one_hundred_minus_risk() -> None:
    ref = PackageRef(name="requests", raw="requests", ecosystem="pypi", source="import")
    info = PackageInfo(name="requests", ecosystem="pypi")

    with pytest.raises(ValidationError, match="trust must equal 100 - risk"):
        PackageVerdict(ref=ref, info=info, risk=25, trust=76, verdict="REVIEW")
