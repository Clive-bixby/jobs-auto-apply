"""FastAPI application for the dashboard: JSON API + built React SPA."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .controller import AutomationController

_MISSING_BUILD = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Dashboard not built</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f8fb;
color:#0f172a;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:28px 32px;max-width:560px}
h1{margin:0 0 8px;font-size:20px}code{background:#eef2ff;padding:2px 7px;border-radius:6px;
font-size:13px}pre{background:#0f172a;color:#e2e8f0;padding:14px 16px;border-radius:10px;
overflow:auto;font-size:13px}</style></head>
<body><div class="card">
<h1>Dashboard bundle not built yet</h1>
<p>The bot API is running at <code>/api/status</code>. Build the UI once:</p>
<pre>cd web
npm install
npm run build</pre>
<p>Then reload this page.</p>
</div></body></html>
"""


def create_app(config_path: Path) -> FastAPI:
    config_path = Path(config_path).resolve()
    base_dir = config_path.parent
    controller = AutomationController(config_path)

    app = FastAPI(title="Jobs Auto-Apply — Dashboard", version="1.0.0")
    app.state.config_path = str(config_path)
    app.state.base_dir = str(base_dir)
    app.state.controller = controller

    @app.middleware("http")
    async def _no_store_shell(request, call_next):  # noqa: ANN001 - ASGI plumbing
        # The SPA shell is not fingerprinted (only its assets are), so a cached
        # copy can pin an old bundle after a rebuild. Never let it be cached.
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response

    app.include_router(router)

    dist = base_dir / "web" / "dist"
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="dashboard")
    else:

        @app.get("/")
        def not_built() -> HTMLResponse:
            return HTMLResponse(_MISSING_BUILD)

    return app


def create_app_from_env() -> FastAPI:
    """uvicorn import-string factory: ``jobs_auto_apply.web.app:create_app_from_env``."""
    import os

    return create_app(Path(os.environ["JAA_CONFIG_PATH"]))
