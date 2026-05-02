from __future__ import annotations

import argparse
import logging
import multiprocessing
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable, Optional
import webbrowser

from fastapi import FastAPI

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None
try:
    import pystray
except Exception:  # pragma: no cover - optional dependency
    pystray = None

logger = logging.getLogger("html_brief_log")


class ServerController:
    def __init__(self, app: FastAPI, host: str, port: int):
        import uvicorn

        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                reload=False,
                access_log=False,
                log_config=None,
            )
        )
        self._stopped = Event()
        self._thread = Thread(target=self._run, name="html-brief-server", daemon=True)

    def _run(self) -> None:
        try:
            self.server.run()
        except Exception:
            logger.exception("Uvicorn server stopped unexpectedly")
            raise
        finally:
            self._stopped.set()

    def start(self) -> None:
        self._thread.start()

    def run_foreground(self) -> None:
        self._run()

    def request_stop(self) -> None:
        self.server.should_exit = True

    def stop(self, timeout: float = 10.0) -> None:
        self.request_stop()
        self._thread.join(timeout=timeout)

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._stopped.wait(timeout=timeout)


def load_tray_icon_image(static_root: Path) -> Any:
    if Image is None:
        raise RuntimeError("Pillow is not available for tray icon support")
    icon_path = static_root / "assets" / "icon.png"
    if not icon_path.exists():
        raise FileNotFoundError(f"Tray icon not found: {icon_path}")
    with Image.open(icon_path) as image:
        return image.copy()


def run_with_tray(app: FastAPI, host: str, port: int, *, static_root: Path) -> None:
    if pystray is None:
        raise RuntimeError("pystray is not installed")

    icon_image = load_tray_icon_image(static_root)
    server = ServerController(app, host, port)
    shutting_down = Event()
    app_url = getattr(app.state, "auto_open_url", None) or f"http://{host}:{port}"
    logger.info(
        "Tray backend initialized: module=%s HAS_MENU=%s HAS_DEFAULT_ACTION=%s",
        getattr(pystray.Icon, "__module__", "unknown"),
        getattr(pystray.Icon, "HAS_MENU", None),
        getattr(pystray.Icon, "HAS_DEFAULT_ACTION", None),
    )

    def request_shutdown(icon: Any) -> None:
        if shutting_down.is_set():
            return
        shutting_down.set()
        logger.info("Tray quit requested")
        server.request_stop()
        icon.stop()

    def open_in_browser(icon: Any, item: Any) -> None:
        del icon, item
        logger.info("Tray default action triggered; opening %s", app_url)
        Thread(target=webbrowser.open, args=(app_url,), daemon=True).start()

    def on_quit(icon: Any, item: Any) -> None:
        del item
        logger.info("Tray menu action triggered: Quit")
        Thread(target=request_shutdown, args=(icon,), daemon=True).start()

    tray_icon = pystray.Icon(
        "html_brief",
        icon=icon_image,
        title="Falcon BMS HTML Briefings",
        menu=pystray.Menu(
            pystray.MenuItem("Open in Browser", open_in_browser, default=True),
            pystray.MenuItem("Quit", on_quit),
        ),
    )
    app.state.shutdown_callback = lambda: request_shutdown(tray_icon)

    def stop_tray_when_server_exits() -> None:
        server.wait()
        request_shutdown(tray_icon)

    server.start()
    Thread(target=stop_tray_when_server_exits, name="html-brief-tray-watch", daemon=True).start()
    try:
        tray_icon.run()
    finally:
        app.state.shutdown_callback = None
        server.stop()


def run_cli(
    *,
    create_app: Callable[..., FastAPI],
    default_config_path: Path,
    static_root: Path,
    is_frozen: bool,
) -> None:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Run the BMS briefing server")
    parser.add_argument(
        "-c",
        "--config",
        default=str(default_config_path),
        help="Path to config ini (default: ./config.ini beside executable)",
    )
    parser.add_argument(
        "-t",
        "--theaters",
        default=None,
        help="Theater ini path or pattern. Supports {version}, e.g. /path/theaters_{version}.ini",
    )
    parser.add_argument("-p", "--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the UI in a browser")
    tray_group = parser.add_mutually_exclusive_group()
    tray_group.add_argument("--tray", action="store_true", help="Run in the system tray")
    tray_group.add_argument("--no-tray", action="store_true", help="Disable the system tray")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()
    app = create_app(config_path=config_path, theater_ini_pattern=args.theaters)

    if not args.no_browser:
        app.state.auto_open_url = f"http://127.0.0.1:{args.port}"

    use_tray = args.tray or (is_frozen and not args.no_tray)

    if use_tray:
        run_with_tray(app, host="127.0.0.1", port=args.port, static_root=static_root)
    else:
        server = ServerController(app, host="127.0.0.1", port=args.port)
        app.state.shutdown_callback = server.request_stop
        try:
            server.run_foreground()
        finally:
            app.state.shutdown_callback = None


__all__ = ["ServerController", "run_cli", "run_with_tray"]
