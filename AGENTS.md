Project: SlopGuard — detects hallucinated/typosquatted/suspicious packages in AI-written code.
Rules: read-only registry lookups only; never install, execute, or publish packages; never store user code.
Scoring is deterministic (LLM only rewrites explanations, and receives only package names + signals, never user code).
Python 3.11, FastAPI, httpx async, pytest.
Only modify files named in the task. Do not refactor or touch working modules. Run tests before and after; all must pass.
core/models.py is the single source of truth for types. HTTP 404 from a registry = package does not exist; timeouts/429/5xx = UNKNOWN, never phantom. Never log user-submitted content. All scoring is deterministic.
