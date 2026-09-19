import json

from typer.testing import CliRunner

from cli import main
from core.models import PackageInfo, ScanResult, ScanSummary


runner = CliRunner()


def registry_mock(monkeypatch, *, exists: bool | None = True, downloads: int = 1_000_000) -> None:
    async def fake_fetch_many(refs):
        return {
            (ref.ecosystem.value, ref.name): PackageInfo(
                name=ref.name,
                ecosystem=ref.ecosystem,
                exists=exists,
                downloads=downloads,
                repo_url="https://github.com/example/source" if exists else None,
                release_count=5 if exists else None,
            )
            for ref in refs
        }

    monkeypatch.setattr(main, "fetch_many", fake_fetch_many)


def test_text_json_and_markdown_formats(monkeypatch, tmp_path) -> None:
    registry_mock(monkeypatch)
    path = tmp_path / "requirements.txt"
    path.write_text("requests==2.31", encoding="utf-8")

    text = runner.invoke(main.app, ["scan", str(path), "--format", "text"])
    structured = runner.invoke(main.app, ["scan", str(path), "--format", "json"])
    markdown = runner.invoke(main.app, ["scan", str(path), "--format", "md"])

    assert text.exit_code == 0
    assert "[OK] requests" in text.stdout
    assert json.loads(structured.stdout)["summary"]["total"] == 1
    assert "| Package | Verdict | Risk | Why |" in markdown.stdout


def test_exit_thresholds_and_usage_error(monkeypatch, tmp_path) -> None:
    registry_mock(monkeypatch, exists=False)
    path = tmp_path / "requirements.txt"
    path.write_text("missing-package", encoding="utf-8")

    assert runner.invoke(main.app, ["scan", str(path), "--fail-on", "block"]).exit_code == 1
    assert runner.invoke(main.app, ["scan", str(path), "--fail-on", "never"]).exit_code == 0
    assert runner.invoke(main.app, ["scan", str(tmp_path / "nope.txt")]).exit_code == 2
    assert runner.invoke(main.app, ["scan", str(path), "--format", "xml"]).exit_code == 2


def test_stdin_unknown_and_no_cache(monkeypatch) -> None:
    registry_mock(monkeypatch, exists=None)
    result = runner.invoke(main.app, ["scan", "-", "--kind", "requirements", "--no-cache"], input="requests\n")

    assert result.exit_code == 0
    assert "1 could not be verified" in result.stdout
    assert "UNKNOWN" in result.stdout


def test_cap_and_version(monkeypatch) -> None:
    registry_mock(monkeypatch)
    seen = []

    def fake_score_all(refs, infos):
        seen.append(len(refs))
        return ScanResult(packages=[], summary=ScanSummary(total=len(refs)), scanned_at=__import__("datetime").datetime.now())

    monkeypatch.setattr(main, "score_all", fake_score_all)
    result = runner.invoke(main.app, ["scan", "-", "--kind", "requirements", "--format", "json"], input="\n".join(f"pkg{i}" for i in range(201)))

    assert result.exit_code == 0
    assert seen == [200]
    assert json.loads(result.stdout)["summary"]["truncated"] is True
    assert runner.invoke(main.app, ["version"]).stdout.strip() == "slopguard 0.1.0"
