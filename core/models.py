"""Shared, validated data contracts for SlopGuard."""

import re
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Ecosystem(str, Enum):
    PYPI = "pypi"
    NPM = "npm"


Source = Literal["requirements", "package_json", "import", "install_cmd"]
Confidence = Literal["declared", "inferred"]
Verdict = Literal["OK", "REVIEW", "RISKY", "BLOCK", "UNKNOWN"]


class PackageRef(BaseModel):
    name: str = Field(min_length=1)
    raw: str = Field(min_length=1)
    ecosystem: Ecosystem
    source: Source
    confidence: Confidence

    @model_validator(mode="before")
    @classmethod
    def derive_confidence(cls, value: object) -> object:
        if isinstance(value, dict) and "confidence" not in value:
            value = {**value, "confidence": "inferred" if value.get("source") == "import" else "declared"}
        return value

    @model_validator(mode="after")
    def normalize_and_validate_confidence(self) -> "PackageRef":
        normalized = self.name.strip().lower()
        if self.ecosystem is Ecosystem.PYPI:
            normalized = re.sub(r"[-_.]+", "-", normalized)
        if not normalized:
            raise ValueError("name must contain non-whitespace characters")

        expected_confidence: Confidence = "inferred" if self.source == "import" else "declared"
        if self.confidence != expected_confidence:
            raise ValueError(f"confidence must be {expected_confidence!r} for source {self.source!r}")

        self.name = normalized
        self.confidence = expected_confidence
        return self


class PackageInfo(BaseModel):
    name: str
    ecosystem: Ecosystem
    exists: bool | None = None
    created_at: datetime | None = None
    release_count: int | None = None
    downloads: int | None = None
    downloads_period: Literal["month", "week"] | None = None
    repo_url: str | None = None
    install_scripts: list[str] = Field(default_factory=list)
    osv_malicious: bool = False
    osv_ids: list[str] = Field(default_factory=list)
    latest_version: str | None = None
    osv_check_failed: bool = False
    lookup_errors: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    signal: str
    points: int
    message: str
    beginner_message: str


class PackageVerdict(BaseModel):
    ref: PackageRef
    info: PackageInfo
    risk: int = Field(ge=0, le=100)
    trust: int = Field(ge=0, le=100)
    verdict: Verdict
    findings: list[Finding] = Field(default_factory=list)
    alternative: str | None = None

    @model_validator(mode="before")
    @classmethod
    def derive_trust(cls, value: object) -> object:
        if isinstance(value, dict) and "trust" not in value and "risk" in value:
            value = {**value, "trust": 100 - value["risk"]}
        return value

    @model_validator(mode="after")
    def validate_trust(self) -> "PackageVerdict":
        expected_trust = 100 - self.risk
        if self.trust != expected_trust:
            raise ValueError("trust must equal 100 - risk")
        self.trust = expected_trust
        return self


class ScanSummary(BaseModel):
    counts: dict[Verdict, int] = Field(default_factory=dict)
    worst_verdict: Verdict = "UNKNOWN"
    total: int = Field(default=0, ge=0)
    truncated: bool = False


class ScanResult(BaseModel):
    packages: list[PackageVerdict] = Field(default_factory=list)
    summary: ScanSummary
    scanned_at: datetime
