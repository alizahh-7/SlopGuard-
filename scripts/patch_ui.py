import sys
from pathlib import Path


def patch(path, pairs):
    p = Path(path)
    text = p.read_bytes().decode("utf-8")
    for old, new in pairs:
        if new in text:
            continue
        n = text.count(old)
        if n != 1:
            print("ABORT " + path + ": expected 1 match, found " + str(n) + " for: " + old[:80])
            sys.exit(1)
        text = text.replace(old, new)
    p.write_bytes(text.encode("utf-8"))
    print("patched " + path)


TRY = (
    "<Explainer onTry={() => { try { sessionStorage.setItem('sg-prefill', JSON.stringify({ v: "
    "'pip install requests slopguard-demo-phantom-pkg-93817', t: Date.now() })) } catch { /* optional */ } "
    "window.location.hash = 'scanner' }} />"
)

patch("web/src/App.jsx", [
    ("import './App.css'",
     "import './App.css'\nimport Explainer from './Explainer.jsx'\nimport FixIt from './FixIt.jsx'"),
    ("{['scanner', 'benchmark', 'about'].map((name) =>",
     "{['scanner', 'learn', 'benchmark', 'about'].map((name) =>"),
    ("view === 'benchmark' ? <Benchmark /> : <About />",
     "view === 'learn' ? " + TRY + " : view === 'benchmark' ? <Benchmark /> : <About />"),
    ("const [content, setContent] = useState('')",
     "const [content, setContent] = useState(() => { try { const raw = sessionStorage.getItem('sg-prefill'); "
     "if (raw) { const saved = JSON.parse(raw); if (Date.now() - saved.t < 10000) return saved.v } } "
     "catch { /* optional */ } return '' })"),
    ("<Results result={result} sorted={sorted} simple={simple} onDownload={download} />",
     "<><Results result={result} sorted={sorted} simple={simple} onDownload={download} />"
     "<FixIt content={content} kind={kind} result={result} url={endpoint('/api/fix')} /></>"),
])

FIX_ROUTE = '''@app.post("/api/fix")
async def fix(payload: ScanRequest):
    from core.remediate import remediate

    result = await scan(payload)
    if isinstance(result, JSONResponse):
        return result
    fixed = remediate(payload.content, payload.kind, result)
    fixed["summary"] = result.summary.model_dump(mode="json")
    return fixed


'''
patch("api/main.py", [
    ('@app.get("/api/samples")', FIX_ROUTE + '@app.get("/api/samples")'),
])
