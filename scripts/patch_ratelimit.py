import sys
from pathlib import Path
p = Path("api/main.py")
t = p.read_bytes().decode("utf-8")
old = 'request.url.path == "/api/scan"'
new = 'request.url.path in ("/api/scan", "/api/fix")'
if new in t:
    print("already patched"); sys.exit(0)
n = t.count(old)
if n != 2:
    print("ABORT: expected 2 matches, found", n); sys.exit(1)
p.write_bytes(t.replace(old, new).encode("utf-8"))
print("patched api/main.py")
