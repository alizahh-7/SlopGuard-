"""Deterministic package-risk signals and curated top-list loading."""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .models import Ecosystem, Finding, PackageInfo, PackageRef

try:  # rapidfuzz is the production dependency; the fallback keeps offline tests usable.
    from rapidfuzz.distance import DamerauLevenshtein
    from rapidfuzz.fuzz import ratio as _ratio
except ImportError:  # pragma: no cover - exercised only where optional dependency is unavailable
    DamerauLevenshtein = None
    from difflib import SequenceMatcher

    def _ratio(left: str, right: str) -> float:
        return SequenceMatcher(None, left, right).ratio() * 100


_DATA = Path(__file__).resolve().parents[1] / "data"
_PYPI_NORMALIZE = re.compile(r"[-_.]+")
_AFFIXES = ("python-", "py-", "-py", "-python", "-official", "-lib", "-js", "-node", "-sdk", "-api", "-client")


def _pypi_name(name: str) -> str:
    return _PYPI_NORMALIZE.sub("-", name.strip().lower())


@lru_cache(maxsize=1)
def load_top_pypi() -> tuple[str, ...]:
    """Load the first 5,000 normalized names from Hugovk or list JSON data."""
    try:
        payload = json.loads((_DATA / "top_pypi.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return ()
    rows = payload.get("rows", []) if isinstance(payload, dict) else payload
    names = (
        row.get("project") if isinstance(row, dict) else row
        for row in rows[:5000]
        if isinstance(row, (dict, str))
    )
    return tuple(dict.fromkeys(_pypi_name(name) for name in names if isinstance(name, str) and name.strip()))


@lru_cache(maxsize=1)
def load_top_npm() -> tuple[str, ...]:
    try:
        payload = json.loads((_DATA / "top_npm.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return ()
    rows = payload.get("rows", []) if isinstance(payload, dict) else payload
    names = (row.get("project") if isinstance(row, dict) else row for row in rows if isinstance(row, (dict, str)))
    return tuple(sorted({name.strip().lower() for name in names if isinstance(name, str) and name.strip()}))


@dataclass(frozen=True)
class SignalContext:
    now: datetime
    pypi_top: tuple[str, ...] = ()
    npm_top: tuple[str, ...] = ()

    def top_for(self, ecosystem: Ecosystem) -> tuple[str, ...]:
        return self.pypi_top if ecosystem is Ecosystem.PYPI else self.npm_top


def default_context(now: datetime | None = None) -> SignalContext:
    return SignalContext(now=now or datetime.now(timezone.utc), pypi_top=load_top_pypi(), npm_top=load_top_npm())


def _distance(left: str, right: str) -> int:
    if DamerauLevenshtein is not None:
        return DamerauLevenshtein.distance(left, right)
    # Optimal-string-alignment Damerau-Levenshtein fallback.
    previous_previous: list[int] | None = None
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            cost = left_char != right_char
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + cost))
            if i > 1 and j > 1 and left_char == right[j - 2] and left[i - 2] == right_char:
                current[-1] = min(current[-1], previous_previous[j - 2] + 1)  # type: ignore[index]
        previous_previous, previous = previous, current
    return previous[-1]


def nearest_top_name(ref: PackageRef, ctx: SignalContext, *, max_distance: int | None = None) -> str | None:
    candidates = ctx.top_for(ref.ecosystem)
    if not candidates:
        return None
    if max_distance is not None:
        matches = [(name, _distance(ref.name, name)) for name in candidates]
        matches = [(name, distance) for name, distance in matches if distance <= max_distance]
        return min(matches, key=lambda item: (item[1], item[0]))[0] if matches else None
    matches = [(name, _ratio(ref.name, name)) for name in candidates]
    matches = [(name, ratio) for name, ratio in matches if ratio >= 80]
    return max(matches, key=lambda item: (item[1], item[0]))[0] if matches else None


def phantom(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if info.exists is not False:
        return None
    if ref.confidence == "inferred":
        return Finding(signal="phantom", points=70, message="The import name was not found, but it may be an alias or a hallucinated module.", beginner_message="This import name was not found, but it could be an alias or an AI mistake.")
    return Finding(signal="phantom", points=100, message="The declared package name does not exist in its public registry.", beginner_message="This name does not exist anywhere, so an attacker could publish malware under it.")


def malicious_advisory(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if info.osv_malicious:
        return Finding(signal="malicious_advisory", points=100, message="A public advisory identifies this package as malicious.", beginner_message="Security researchers have identified this package as malware.")
    return None


def historical_advisory(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if info.osv_check_failed or info.osv_malicious or not info.latest_version:
        return None
    if any(identifier.startswith("MAL-") for identifier in info.osv_ids):
        return Finding(signal="historical_advisory", points=0, message="An advisory exists for older versions only", beginner_message="A past version of this package was reported as malicious. The current version is not affected.")
    return None


def advisory_unconfirmed(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if info.osv_check_failed:
        return Finding(signal="advisory_unconfirmed", points=0, message="An advisory exists but could not be confirmed against the latest version", beginner_message="A security advisory exists, but we could not confirm whether the current version is affected.")
    return None


def typosquat(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    top = ctx.top_for(ref.ecosystem)
    if ref.name in top or len(ref.name) < 4:
        return None
    limit = 1 if len(ref.name) <= 7 else 2
    lookalike = nearest_top_name(ref, ctx, max_distance=limit)
    if lookalike:
        return Finding(signal="typosquat", points=40, message=f"This name closely resembles the popular package {lookalike}.", beginner_message=f"This name looks almost the same as the well-known package {lookalike}, which can be a trick.")
    return None


def lookalike_affix(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    top = set(ctx.top_for(ref.ecosystem))
    if ref.name in top:
        return None
    for affix in _AFFIXES:
        candidate = ref.name[len(affix):] if affix.endswith("-") and ref.name.startswith(affix) else ref.name[: -len(affix)] if affix.startswith("-") and ref.name.endswith(affix) else None
        if candidate in top:
            return Finding(signal="lookalike_affix", points=25, message=f"This name adds or removes a common affix from the popular package {candidate}.", beginner_message=f"This name is a small variation of the well-known package {candidate}.")
    return None


def very_new(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if info.created_at is None:
        return None
    created = info.created_at if info.created_at.tzinfo else info.created_at.replace(tzinfo=timezone.utc)
    now = ctx.now if ctx.now.tzinfo else ctx.now.replace(tzinfo=timezone.utc)
    age_days = (now - created).total_seconds() / 86400
    if age_days < 30:
        return Finding(signal="very_new", points=35, message="The package was first released less than 30 days ago.", beginner_message="This package is very new and has not had much time to earn trust.")
    if age_days < 90:
        return Finding(signal="very_new", points=15, message="The package was first released less than 90 days ago.", beginner_message="This package is still quite new.")
    return None


def low_downloads(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if info.downloads is None:
        return None
    if ref.ecosystem is Ecosystem.PYPI:
        points = 25 if info.downloads < 500 else 10 if info.downloads < 5000 else 0
    else:
        points = 25 if info.downloads < 100 else 10 if info.downloads < 1000 else 0
    if points:
        return Finding(signal="low_downloads", points=points, message="The package has very few recent downloads for its ecosystem.", beginner_message="Very few people appear to be using this package recently.")
    return None


def no_repo(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if info.exists is True and info.repo_url is None:
        return Finding(signal="no_repo", points=15, message="The package has no published source repository link.", beginner_message="There is no link to the source code, so it is harder to inspect.")
    return None


def single_release(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if info.release_count == 1:
        return Finding(signal="single_release", points=10, message="The package has only one published release.", beginner_message="This package has only been published once.")
    return None


def install_script(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if ref.ecosystem is Ecosystem.NPM and info.install_scripts:
        names = ", ".join(info.install_scripts)
        return Finding(signal="install_script", points=20, message=f"The package runs install-time scripts: {names}.", beginner_message="This package runs code automatically when it is installed.")
    return None


def lookup_failed(ref: PackageRef, info: PackageInfo, ctx: SignalContext) -> Finding | None:
    if info.exists is None:
        return Finding(signal="lookup_failed", points=0, message="could not verify (network/rate limit); not treated as safe or unsafe.", beginner_message="We could not check this package right now, so it is not marked safe or unsafe.")
    return None


SIGNALS: list[Callable[[PackageRef, PackageInfo, SignalContext], Finding | None]] = [
    phantom, malicious_advisory, historical_advisory, advisory_unconfirmed, typosquat, lookalike_affix, very_new, low_downloads, no_repo, single_release, install_script, lookup_failed,
]
