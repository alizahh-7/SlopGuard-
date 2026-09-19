import asyncio
import json
from pathlib import Path

from bench.analyze import build_summary
from bench.providers import RateLimiter
from bench.run import ROOT, parse_dependencies, parser, run_benchmark


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "bench"
    (root / "fixtures").mkdir(parents=True)
    prompts = [
        {"id": "py", "language": "python", "category": "mainstream", "task": "a task"},
        {"id": "js", "language": "javascript", "category": "mainstream", "task": "a task"},
    ]
    (root / "prompts.json").write_text(json.dumps(prompts), encoding="utf-8")
    (root / "fixtures" / "dry_run.json").write_text(json.dumps({"python": "requests>=2\n", "javascript": "{\"dependencies\":{\"react\":\"^1\"}}"}), encoding="utf-8")
    return root


def args(*values: str):
    return parser().parse_args(["--dry-run", "--models", "gemini", "--runs", "1", *values])


def test_dry_run_end_to_end_writes_public_summary(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    summary = asyncio.run(run_benchmark(args("--limit", "2", "--max-calls", "2"), root))
    assert summary["models"]["gemini"]["calls"] == 2
    assert (root / "results" / "summary.json").exists()
    assert (root / "results" / "private" / "raw.jsonl").exists()


def test_resume_uses_cached_response(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    asyncio.run(run_benchmark(args("--limit", "1", "--max-calls", "1"), root))
    (root / "fixtures" / "dry_run.json").write_text(json.dumps({"python": "changed>=1\n", "javascript": "{}"}), encoding="utf-8")
    asyncio.run(run_benchmark(args("--limit", "1", "--max-calls", "0"), root))
    raw = (root / "results" / "private" / "raw.jsonl").read_text(encoding="utf-8")
    assert "requests" in raw and "changed" not in raw


def test_budget_stops_before_second_call(tmp_path: Path) -> None:
    root = make_root(tmp_path)
    summary = asyncio.run(run_benchmark(args("--limit", "2", "--max-calls", "1"), root))
    assert summary["models"]["gemini"]["calls"] == 1


def test_parse_fenced_unfenced_and_json() -> None:
    assert [ref.name for ref in parse_dependencies("```\nrequests>=2\n```", "python")] == ["requests"]
    assert [ref.name for ref in parse_dependencies("pydantic>=2", "python")] == ["pydantic"]
    assert [ref.name for ref in parse_dependencies("```json\n{\"dependencies\":{\"react\":\"1\"}}\n```", "javascript")] == ["react"]


def test_masking_never_leaks_raw_phantom_name() -> None:
    raw_name = "privatephantomname"
    summary = build_summary([{ "model": "m", "prompt_id": "p", "run": 1, "ok": True, "packages": [{"name": raw_name, "ecosystem": "pypi", "exists": False, "verdict": "BLOCK"}] }])
    rendered = json.dumps(summary)
    assert raw_name not in rendered
    assert "pri***18" in rendered


def test_rate_limiter_spaces_requests() -> None:
    class Clock:
        value = 0.0
        def __call__(self):
            return self.value
    clock = Clock()
    sleeps = []
    async def sleep(delay):
        sleeps.append(delay)
        clock.value += delay
    limiter = RateLimiter(10, clock=clock, sleep=sleep)
    asyncio.run(limiter.wait())
    asyncio.run(limiter.wait())
    assert sleeps == [6.0]
