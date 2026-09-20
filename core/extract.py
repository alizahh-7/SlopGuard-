"""Pure dependency extraction helpers; this module never performs I/O."""

import ast
import json
import re
import shlex
import sys
from collections.abc import Iterable

from .models import Ecosystem, PackageRef


# Import names that differ from their PyPI distribution names.
IMPORT_TO_PACKAGE = {
    "PIL": "pillow", "Crypto": "pycryptodome", "MySQLdb": "mysqlclient",
    "OpenSSL": "pyopenssl", "attr": "attrs", "babel": "babel", "bs4": "beautifulsoup4", "serial": "pyserial",
    "cv2": "opencv-python", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
    "docx": "python-docx", "fitz": "pymupdf", "google.generativeai": "google-generativeai",
    "jwt": "pyjwt", "magic": "python-magic", "skimage": "scikit-image",
    "sklearn": "scikit-learn", "telegram": "python-telegram-bot", "yaml": "pyyaml",
    "aiohttp": "aiohttp", "aiosqlite": "aiosqlite", "asyncpg": "asyncpg",
    "boto3": "boto3", "celery": "celery", "cffi": "cffi", "click": "click",
    "cryptography": "cryptography", "discord": "py-cord", "fastapi": "fastapi",
    "flask": "flask", "gevent": "gevent", "gunicorn": "gunicorn", "httpx": "httpx",
    "jinja2": "jinja2", "kubernetes": "kubernetes", "lxml": "lxml", "matplotlib": "matplotlib",
    "motor": "motor", "numpy": "numpy", "openai": "openai", "pandas": "pandas",
    "paramiko": "paramiko", "pexpect": "pexpect", "psutil": "psutil", "pydantic": "pydantic",
    "pymongo": "pymongo", "pytest": "pytest", "redis": "redis", "requests": "requests",
    "rich": "rich", "scipy": "scipy", "selenium": "selenium", "setuptools": "setuptools",
    "sqlalchemy": "sqlalchemy", "starlette": "starlette", "tensorflow": "tensorflow",
    "torch": "torch", "tqdm": "tqdm", "twilio": "twilio", "typing_extensions": "typing-extensions",
    "uvicorn": "uvicorn", "websockets": "websockets", "werkzeug": "werkzeug",
    "win32api": "pywin32", "xlsxwriter": "xlsxwriter", "xmltodict": "xmltodict",
}

_PYPI_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_NPM_NAME = re.compile(r"^(?:@[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*|[A-Za-z0-9][A-Za-z0-9._-]*)$")
_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
_NODE_BUILTINS = {
    "assert", "buffer", "child_process", "cluster", "console", "constants", "crypto", "dgram",
    "diagnostics_channel", "dns", "domain", "events", "fs", "http", "http2", "https", "module",
    "net", "os", "path", "perf_hooks", "process", "punycode", "querystring", "readline", "repl",
    "stream", "string_decoder", "sys", "timers", "tls", "trace_events", "tty", "url", "util", "v8",
    "vm", "wasi", "worker_threads", "zlib",
}
_REQ_OPTIONS = ("-r", "-c", "-e", "-i", "--index-url", "--extra-index-url", "--find-links")


def _ref(name: str, raw: str, ecosystem: Ecosystem, source: str) -> PackageRef | None:
    name = name.strip()
    if ecosystem is Ecosystem.PYPI:
        if not _PYPI_NAME.fullmatch(name):
            return None
        normalized = re.sub(r"[-_.]+", "-", name.lower())
    else:
        if not _NPM_NAME.fullmatch(name):
            return None
        normalized = name.lower()
    return PackageRef(name=normalized, raw=raw, ecosystem=ecosystem, source=source)


def _dedupe(refs: Iterable[PackageRef]) -> list[PackageRef]:
    result: dict[tuple[Ecosystem, str], PackageRef] = {}
    for ref in refs:
        key = (ref.ecosystem, ref.name)
        previous = result.get(key)
        if previous is None or (previous.confidence == "inferred" and ref.confidence == "declared"):
            result[key] = ref
    return list(result.values())


def _requirements(content: str) -> list[PackageRef]:
    refs: list[PackageRef] = []
    for original in content.splitlines():
        line = original.strip()
        if not line or line.startswith("#") or line.startswith(_REQ_OPTIONS):
            continue
        line = re.split(r"\s+#", line, maxsplit=1)[0].split(";", maxsplit=1)[0].strip()
        line = re.split(r"\s+--hash(?:=|\s)", line, maxsplit=1)[0].strip()
        if not line or line.startswith(_REQ_OPTIONS) or re.match(r"(?:git\+|https?://|file:|\./|\.\./)", line, re.I):
            continue
        if re.search(r"\s@\s*(?:git\+|https?://|file:|\.?\./)", line, re.I):
            continue
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?", line)
        if match:
            ref = _ref(match.group(1), match.group(1), Ecosystem.PYPI, "requirements")
            if ref:
                refs.append(ref)
    return refs


def _package_json(content: str) -> list[PackageRef]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed package.json: {exc.msg}") from exc
    if not isinstance(data, dict):
        return []
    refs: list[PackageRef] = []
    for section in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        dependencies = data.get(section, {})
        if isinstance(dependencies, dict):
            for name in dependencies:
                if isinstance(name, str):
                    ref = _ref(name, name, Ecosystem.NPM, "package_json")
                    if ref:
                        refs.append(ref)
    return refs


def _python_names(content: str) -> list[str]:
    try:
        tree = ast.parse(content)
        names: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.append(node.module)
        return names
    except SyntaxError:
        names = []
        for match in re.finditer(r"(?m)^\s*import\s+([A-Za-z_][\w.]*)(?:\s+as\s+\w+)?", content):
            names.append(match.group(1))
        for match in re.finditer(r"(?m)^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+", content):
            names.append(match.group(1))
        return names


def _python(content: str) -> list[PackageRef]:
    refs: list[PackageRef] = []
    for dotted_name in _python_names(content):
        root = dotted_name.split(".", maxsplit=1)[0]
        if root in _STDLIB:
            continue
        package = IMPORT_TO_PACKAGE.get(dotted_name, IMPORT_TO_PACKAGE.get(root, root))
        ref = _ref(package, root, Ecosystem.PYPI, "import")
        if ref:
            refs.append(ref)
    return refs


_JS_PATTERNS = (
    re.compile(r"\bimport\s+(?:[^'\"\n]*?\s+from\s+)?['\"]([^'\"\n]+)['\"]"),
    re.compile(r"\brequire\s*\(\s*['\"]([^'\"\n]+)['\"]\s*\)"),
    re.compile(r"\bimport\s*\(\s*['\"]([^'\"\n]+)['\"]\s*\)"),
    re.compile(r"\bexport\s+(?:[^'\"\n]*?\s+from\s+)['\"]([^'\"\n]+)['\"]"),
)


def _npm_root(value: str) -> str | None:
    value = value.strip()
    if not value or value.startswith((".", "/", "@/", "~/", "node:")):
        return None
    if value.startswith("@"):
        parts = value.split("/")
        if len(parts) < 2:
            return None
        root = "/".join(parts[:2])
    else:
        root = value.split("/", maxsplit=1)[0]
    return None if root in _NODE_BUILTINS else root


def _javascript(content: str) -> list[PackageRef]:
    refs: list[PackageRef] = []
    for pattern in _JS_PATTERNS:
        for match in pattern.finditer(content):
            root = _npm_root(match.group(1))
            if root:
                ref = _ref(root, root, Ecosystem.NPM, "import")
                if ref:
                    refs.append(ref)
    return refs


_COMMAND = re.compile(
    r"(?i)(?<![\w-])(?:pip(?:3)?\s+install|python(?:\d+(?:\.\d+)?)?\s+-m\s+pip\s+install|npm\s+(?:install|i|add)|yarn\s+add|pnpm\s+add)\b"
)


def _install_name(token: str, ecosystem: Ecosystem) -> tuple[str, str] | None:
    token = token.strip()
    if ecosystem is Ecosystem.PYPI:
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?(?:[<>=!~].*)?$", token)
        return (match.group(1), match.group(1)) if match else None
    if token.startswith("@"):
        slash = token.find("/")
        if slash < 1:
            return None
        at = token.find("@", slash)
    else:
        at = token.find("@")
    name = token if at <= 0 else token[:at]
    return (name, name) if _NPM_NAME.fullmatch(name) else None


def _installs(content: str) -> list[PackageRef]:
    content = content.replace("\\\r\n", " ").replace("\\\n", " ")
    refs: list[PackageRef] = []
    for line in content.splitlines():
        commands = list(_COMMAND.finditer(line))
        for index, command in enumerate(commands):
            end = commands[index + 1].start() if index + 1 < len(commands) else len(line)
            arguments = re.split(r"(?:&&|\|\||;)", line[command.end():end], maxsplit=1)[0]
            try:
                tokens = shlex.split(arguments)
            except ValueError:
                tokens = arguments.split()
            ecosystem = Ecosystem.NPM if command.group().lower().startswith(("npm", "yarn", "pnpm")) else Ecosystem.PYPI
            skip_next = False
            for token in tokens:
                if skip_next:
                    skip_next = False
                    continue
                if token in {"-r", "-c", "-i", "--index-url", "--extra-index-url", "--find-links", "-e"}:
                    skip_next = True
                    continue
                if token.startswith("-") or token in {"-g", "--save-dev", "-D"}:
                    continue
                parsed = _install_name(token, ecosystem)
                if parsed:
                    name, raw = parsed
                    ref = _ref(name, raw, ecosystem, "install_cmd")
                    if ref:
                        refs.append(ref)
    return refs


def _auto_kinds(content: str, filename: str | None) -> set[str]:
    kinds: set[str] = set()
    suffix = (filename or "").lower().rsplit(".", maxsplit=1)[-1]
    kinds.update({"python"} if suffix == "py" else {"javascript"} if suffix in {"js", "jsx", "ts", "tsx"} else set())
    try:
        data = json.loads(content)
        if isinstance(data, dict) and any(key in data for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")):
            kinds.add("package_json")
    except json.JSONDecodeError:
        pass
    if re.search(r"\brequire\s*\(|\bimport\s+[^\n;]+\s+from\s+['\"]|\b(?:const|let|var)\s+|=>", content):
        kinds.add("javascript")
    if re.search(r"(?m)^\s*(?:def\s+\w+|from\s+[A-Za-z_][\w.]*\s+import)\b", content) or re.search(
        r"(?m)^\s*import\s+(?![^\n]*\sfrom\s+['\"])[A-Za-z_]", content
    ):
        kinds.add("python")
    if any(
        len(line.strip()) <= 255 and re.match(r"\s*[A-Za-z0-9][\w.-]*(?:\[[^]]+\])?\s*(?:[<>=!~]|$)", line)
        for line in content.splitlines()
        if line.strip()
    ):
        kinds.add("requirements")
    return kinds


def _extract_kind(content: str, kind: str) -> list[PackageRef]:
    if kind == "requirements":
        return _requirements(content)
    if kind == "package_json":
        return _package_json(content)
    if kind == "python":
        return _python(content)
    if kind == "javascript":
        return _javascript(content)
    if kind == "text":
        return _installs(content)
    raise ValueError(f"Unsupported extraction kind: {kind}")


def extract(content: str, kind: str = "auto", filename: str | None = None) -> list[PackageRef]:
    """Extract package references from text without accessing the network or filesystem."""
    if kind not in {"auto", "requirements", "package_json", "python", "javascript", "text"}:
        raise ValueError(f"Unsupported extraction kind: {kind}")
    if not content.strip():
        return []
    if kind != "auto":
        return _dedupe(_extract_kind(content, kind))

    refs: list[PackageRef] = _installs(content)
    fence = re.compile(r"(?ms)^```\s*([\w-]*)\s*\n(.*?)^```\s*$")
    fenced_spans: list[tuple[int, int]] = []
    language_kinds = {"python": "python", "py": "python", "javascript": "javascript", "js": "javascript", "ts": "javascript", "tsx": "javascript", "json": "package_json", "bash": "text", "sh": "text", "requirements": "requirements", "txt": "requirements"}
    for match in fence.finditer(content):
        fenced_spans.append(match.span())
        tagged_kind = language_kinds.get(match.group(1).lower())
        if tagged_kind:
            refs.extend(_extract_kind(match.group(2), tagged_kind))
        else:
            for detected_kind in _auto_kinds(match.group(2), filename):
                refs.extend(_extract_kind(match.group(2), detected_kind))
    remainder = "".join(content[last:start] for last, start in zip([0, *[end for _, end in fenced_spans]], [start for start, _ in fenced_spans]))
    if not fenced_spans:
        remainder = content
    elif fenced_spans:
        remainder += content[fenced_spans[-1][1]:]
    for detected_kind in _auto_kinds(remainder, filename):
        refs.extend(_extract_kind(remainder, detected_kind))
    return _dedupe(refs)
