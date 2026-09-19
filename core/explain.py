"""Template-only one-line verdict renderers."""

from .models import PackageVerdict


def render_technical(verdict: PackageVerdict) -> str:
    signals = ", ".join(finding.signal for finding in verdict.findings) or "no risk signals"
    return f"{verdict.ref.name}: {verdict.verdict} (risk {verdict.risk}/100; {signals})."


def render_beginner(verdict: PackageVerdict) -> str:
    messages = " ".join(finding.beginner_message for finding in verdict.findings) or "No known warning signs were found."
    return f"{verdict.ref.name}: {verdict.verdict}. {messages}"


def render(verdict: PackageVerdict, *, beginner: bool = False) -> str:
    return render_beginner(verdict) if beginner else render_technical(verdict)
