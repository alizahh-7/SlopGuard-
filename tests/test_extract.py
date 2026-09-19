import time

import pytest

from core.extract import extract


@pytest.mark.parametrize(
    ("content", "kind", "expected"),
    [
        ("requests==2.31", "requirements", ["requests"]),
        ("Requests[security]>=2", "requirements", ["requests"]),
        ("flask; python_version > '3.10'", "requirements", ["flask"]),
        ("httpx # client", "requirements", ["httpx"]),
        ("numpy --hash=sha256:abc", "requirements", ["numpy"]),
        ("-r base.txt\nclick", "requirements", ["click"]),
        ("--index-url https://example.test\nrich", "requirements", ["rich"]),
        ("git+https://github.com/a/b.git", "requirements", []),
        ("https://example.test/pkg.whl", "requirements", []),
        ("./local-project", "requirements", []),
        ('{"dependencies":{"React":"^18", "@scope/pkg":"file:../pkg"}}', "package_json", ["react", "@scope/pkg"]),
        ('{"devDependencies":{"vite":"latest"}}', "package_json", ["vite"]),
        ('{"optionalDependencies":{"left-pad":"git+https://x"}}', "package_json", ["left-pad"]),
        ('{"peerDependencies":{"vue":"workspace:*"}}', "package_json", ["vue"]),
        ("import requests", "python", ["requests"]),
        ("import sklearn.metrics", "python", ["scikit-learn"]),
        ("from PIL.Image import open", "python", ["pillow"]),
        ("from google.generativeai import GenerativeModel", "python", ["google-generativeai"]),
        ("import os\nimport json", "python", []),
        ("from . import local", "python", []),
        ("from ..thing import local", "python", []),
        ("import yaml as y", "python", ["pyyaml"]),
        ("import cv2\nimport bs4", "python", ["opencv-python", "beautifulsoup4"]),
        ("import requests\nnot valid python", "python", ["requests"]),
        ("import lodash from 'lodash/fp'", "javascript", ["lodash"]),
        ("import '@scope/pkg/sub'", "javascript", ["@scope/pkg"]),
        ("const x = require('react')", "javascript", ["react"]),
        ("const x = import('vite')", "javascript", ["vite"]),
        ("export { x } from 'date-fns/format'", "javascript", ["date-fns"]),
        ("import fs from 'fs'", "javascript", []),
        ("import 'node:path'", "javascript", []),
        ("import x from './local'", "javascript", []),
        ("import x from '@/alias'", "javascript", []),
        ("import x from '~/alias'", "javascript", []),
        ("pip install requests==2.31 rich[markdown]", "text", ["requests", "rich"]),
        ("python -m pip install 'flask>=2'", "text", ["flask"]),
        ("npm i react@18 @scope/pkg@1", "text", ["react", "@scope/pkg"]),
        ("yarn add vue@latest", "text", ["vue"]),
        ("pnpm add zod", "text", ["zod"]),
        ("pip install -r requirements.txt -c constraints.txt click", "text", ["click"]),
        ("npm install -D typescript --save-dev", "text", ["typescript"]),
        ("pip install requests && npm install react", "text", ["requests", "react"]),
        ("pip install \\\n+            httpx \\\n+            rich", "text", ["httpx", "rich"]),
    ],
)
def test_extract_sources(content: str, kind: str, expected: list[str]) -> None:
    assert [ref.name for ref in extract(content, kind)] == expected


def test_auto_fenced_markdown_mixes_languages() -> None:
    content = """```python
import requests
```
```bash
pip install rich
```
```json
{"dependencies": {"react": "^18"}}
```
"""
    refs = extract(content)
    assert {(ref.ecosystem.value, ref.name, ref.confidence) for ref in refs} == {
        ("pypi", "requests", "inferred"),
        ("pypi", "rich", "declared"),
        ("npm", "react", "declared"),
    }


def test_declared_reference_wins_over_inferred_duplicate() -> None:
    refs = extract("import requests\npip install requests")
    assert len(refs) == 1
    assert refs[0].source == "install_cmd"
    assert refs[0].confidence == "declared"


def test_auto_javascript_import_is_not_also_a_python_import() -> None:
    refs = extract("import react from 'react'")
    assert [(ref.ecosystem.value, ref.name) for ref in refs] == [("npm", "react")]


def test_empty_input_and_invalid_names_are_ignored() -> None:
    assert extract("") == []
    assert extract("pip install !!!", "text") == []


def test_bad_package_json_is_clear_error() -> None:
    with pytest.raises(ValueError, match="Malformed package.json"):
        extract("{not json", "package_json")


def test_large_junk_completes_quickly() -> None:
    started = time.monotonic()
    assert extract("x" * 200_000) == []
    assert time.monotonic() - started < 1
