import json
from types import SimpleNamespace as NS

from core.remediate import remediate


def item(name, verdict, alt=None, eco="pypi", msg="bad package"):
    return NS(
        ref=NS(name=name, ecosystem=eco),
        verdict=verdict,
        alternative=alt,
        findings=[NS(beginner_message=msg, message=msg)],
    )


def res(*items):
    return NS(packages=list(items))


def test_requirements_removes_phantom_keeps_ok():
    content = "requests==2.31.0\nbadpkg==1.0\n"
    out = remediate(content, "requirements", res(item("requests", "OK"), item("badpkg", "BLOCK")))
    assert "requests==2.31.0" in out["fixed_content"]
    assert "# SlopGuard removed: badpkg" in out["fixed_content"]
    assert out["changed_count"] == 1
    assert "-badpkg==1.0" in out["diff"]


def test_replace_drops_version_pin_and_needs_review():
    out = remediate("reqeusts==1.0\n", "requirements", res(item("reqeusts", "RISKY", alt="requests")))
    assert out["fixed_content"].startswith("requests  # SlopGuard: replaced reqeusts")
    assert "==1.0" not in out["fixed_content"]
    assert out["needs_review_count"] == 1


def test_package_json_removes_key():
    content = '{"dependencies": {"express": "^4", "evilpkg": "1.0.0"}}'
    out = remediate(content, "package_json", res(item("evilpkg", "BLOCK", eco="npm"), item("express", "OK", eco="npm")))
    assert json.loads(out["fixed_content"]) == {"dependencies": {"express": "^4"}}


def test_install_command_line():
    out = remediate("pip install requests badpkg", "text", res(item("requests", "OK"), item("badpkg", "BLOCK")))
    assert out["fixed_content"].startswith("pip install requests")
    assert "badpkg" not in out["fixed_content"].split("#")[0]


def test_imports_are_not_rewritten():
    out = remediate("import badpkg\n", "python", res(item("badpkg", "BLOCK")))
    assert out["supported"] is False
    assert out["fixed_content"] == "import badpkg\n"
    assert out["changes"][0]["action"] == "manual"


def test_nothing_risky_means_no_changes():
    out = remediate("requests\n", "requirements", res(item("requests", "OK")))
    assert out["changed_count"] == 0 and out["diff"] == ""
