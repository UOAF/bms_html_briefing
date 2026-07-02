from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


class NoCacheAppStaticFiles(StaticFiles):
    """StaticFiles variant that prevents stale app JS/CSS during local updates."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if path.endswith((".js", ".css")):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


def register_file_routes(
    app: FastAPI,
    *,
    static_root: Path,
    web_dir: Path,
    kneeboards_dir: Path,
    resolve_path: Callable[[str], Path],
    app_version: str,
) -> None:
    """Register static mounts and simple file-serving endpoints."""

    app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")
    app.mount("/templates", NoCacheAppStaticFiles(directory=static_root / "templates"), name="templates")
    app.mount("/dist", StaticFiles(directory=static_root / "dist"), name="dist")
    app.mount("/kneeboards", StaticFiles(directory=kneeboards_dir), name="kneeboards")
    if web_dir.exists():
        app.mount("/web", StaticFiles(directory=web_dir), name="web")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        ui_path = web_dir / "index.html"
        if not ui_path.exists():
            raise HTTPException(status_code=500, detail="UI not found. Did you delete web/index.html?")
        html = ui_path.read_text(encoding="utf-8").replace("__APP_VERSION__", app_version)
        return HTMLResponse(html)

    @app.get("/api/logs")
    def get_logs() -> JSONResponse:
        logs = list(app.state.ui_handler.buffer)
        return JSONResponse(content=logs)

    @app.get("/brief")
    def serve_brief() -> FileResponse:
        last_brief = getattr(app.state, "last_brief_path", None)
        output_file = Path(last_brief) if last_brief else resolve_path(app.state.cfg["system"]["output_dir"]) / "index.html"
        if not output_file.exists():
            raise HTTPException(status_code=404, detail="No generated briefing found. Run /api/generate first.")
        return FileResponse(output_file)

    @app.get("/pdf")
    def serve_pdf() -> FileResponse:
        last_pdf = getattr(app.state, "last_pdf_path", None)
        pdf_file = Path(last_pdf) if last_pdf else resolve_path(app.state.cfg["system"]["pdf_output_dir"]) / "kneeboard.pdf"
        if not pdf_file.exists():
            raise HTTPException(status_code=404, detail="No generated PDF found. Run /api/pdf first.")
        return FileResponse(pdf_file)


__all__ = ["register_file_routes"]
