"""Safe dependency remediation. Produces suggestions only.
Never installs, executes or publishes anything."""
from __future__ import annotations

import difflib
import json
import re

BAD = {"RISKY", "BLOCK"}
JSON_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
REQ_LINE = re.compile(r"^(\s*)([A-Za-z0-9][A-Za-z0-9._-]*)(\s*\[[^\]]*\])?(\s*(?:[<>=!~]=?|===).*)?$")
INSTALL_LINE = re.compile(r"\b(pip3?|npm|yarn|pnpm)\b.*\b(install|i|add)\b", re.I)
INSTALL_WORDS = ("install", "i", "add")


def _val(x):
    return str(getattr(x, "value", x))


def _norm(name, eco):
    name = name.strip().lower()
    return re.sub(r"[-_.]+", "-", name) if eco == "pypi" else name


def _reason(item):
    for f in item.findings or []:
        msg = getattr(f, "beginner_message", None) or getattr(f, "message", None)
        if msg:
            return msg
    return "Flagged as risky by SlopGuard."


def _change(item, action, replacement=None):
    return {
        "package": item.ref.name,
        "ecosystem": _val(item.ref.ecosystem).lower(),
        "verdict": _val(item.verdict).upper(),
        "action": action,
        "replacement": replacement,
        "reason": _reason(item),
        "needs_review": bool(replacement) or action == "manual",
    }


def _tok_name(tok, eco):
    if eco == "npm":
        if tok.startswith("@"):
            return "@" + tok[1:].split("@")[0]
        return tok.split("@")[0]
    return re.split(r"[<>=!~\[;@]", tok)[0]


def _fix_install(line, code, bad):
    tokens = code.split()
    idx = next((i for i, t in enumerate(tokens) if t.lower() in INSTALL_WORDS), None)
    if idx is None:
        return line, []
    eco = "pypi" if re.search(r"\bpip3?\b", code, re.I) else "npm"
    head, tail = tokens[: idx + 1], tokens[idx + 1 :]
    new_tail, changes, notes = [], [], []
    for tok in tail:
        bare = tok.strip("'\"")
        if bare.startswith(("-", ".", "/")) or "://" in bare:
            new_tail.append(tok)
            continue
        item = bad.get((eco, _norm(_tok_name(bare, eco), eco)))
        if item is None:
            new_tail.append(tok)
            continue
        alt = getattr(item, "alternative", None)
        if alt:
            new_tail.append(alt)
            changes.append(_change(item, "replace", alt))
            notes.append("replaced " + item.ref.name)
        else:
            changes.append(_change(item, "remove"))
            notes.append("removed " + item.ref.name)
    if not changes:
        return line, []
    if any(not t.startswith("-") for t in new_tail):
        return " ".join(head + new_tail) + "  # SlopGuard: " + "; ".join(notes), changes
    return "# SlopGuard removed: " + line.strip(), changes


def _fix_text(content, bad):
    out, changes = [], []
    for line in content.splitlines():
        code, _, _c = line.partition(" #")
        stripped = code.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        if INSTALL_LINE.search(code):
            new_line, made = _fix_install(line, code, bad)
            out.append(new_line)
            changes.extend(made)
            continue
        m = REQ_LINE.match(code.rstrip())
        if not m:
            out.append(line)
            continue
        item = bad.get(("pypi", _norm(m.group(2), "pypi")))
        if item is None:
            out.append(line)
            continue
        alt = getattr(item, "alternative", None)
        if alt:
            out.append(m.group(1) + alt + "  # SlopGuard: replaced " + m.group(2) + ", verify before installing")
            changes.append(_change(item, "replace", alt))
        else:
            out.append("# SlopGuard removed: " + m.group(2))
            changes.append(_change(item, "remove"))
    return out, changes


def _fix_json(content, bad):
    try:
        data = json.loads(content)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    changes = []
    for section in JSON_SECTIONS:
        deps = data.get(section)
        if not isinstance(deps, dict):
            continue
        for name in list(deps):
            item = bad.get(("npm", _norm(name, "npm")))
            if item is None:
                continue
            del deps[name]
            alt = getattr(item, "alternative", None)
            changes.append(_change(item, "remove", alt))
    m = re.search(r"\n([ \t]+)\S", content)
    indent = m.group(1) if m else 2
    return json.dumps(data, indent=indent, ensure_ascii=False) + "\n", changes


def remediate(content, kind, result):
    k = (kind or "auto").lower()
    bad = {}
    for item in result.packages:
        if _val(item.verdict).upper() in BAD:
            eco = _val(item.ref.ecosystem).lower()
            bad[(eco, _norm(item.ref.name, eco))] = item
    out = {
        "supported": True,
        "fixed_content": content,
        "diff": "",
        "changes": [],
        "changed_count": 0,
        "needs_review_count": 0,
    }
    if not bad:
        return out
    changes, fixed = [], None
    if k in ("python", "javascript"):
        out["supported"] = False
    else:
        if k in ("package_json", "auto") and content.lstrip().startswith("{"):
            res = _fix_json(content, bad)
            if res:
                fixed, changes = res
        if fixed is None:
            lines, changes = _fix_text(content, bad)
            fixed = "\n".join(lines) + ("\n" if content.endswith("\n") else "")
    covered = {(c["ecosystem"], _norm(c["package"], c["ecosystem"])) for c in changes}
    for key, item in bad.items():
        if key not in covered:
            changes.append(_change(item, "manual", getattr(item, "alternative", None)))
    if fixed is not None:
        out["fixed_content"] = fixed
        if fixed != content:
            out["diff"] = "\n".join(
                difflib.unified_diff(content.splitlines(), fixed.splitlines(), "original", "fixed", lineterm="")
            )
    out["changes"] = changes
    out["changed_count"] = sum(1 for c in changes if c["action"] in ("replace", "remove"))
    out["needs_review_count"] = sum(1 for c in changes if c["needs_review"])
    return out
