from __future__ import annotations

import logging
import socket
from pathlib import Path

from aiohttp import web

from combat.board import apply_web_action, board_snapshot
from combat.storage import get_combat
from config import EDITOR_HOST, EDITOR_PORT, EDITOR_PUBLIC_URL

logger = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
MAP_EDITOR_FILE = TOOLS_DIR / "map-editor.html"
COMBAT_BOARD_FILE = TOOLS_DIR / "combat-board.html"

_runner: web.AppRunner | None = None
_bound_host = ""
_bound_port = 0


def _lan_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


def editor_is_running() -> bool:
    return _runner is not None


def editor_public_url() -> str | None:
    if EDITOR_PUBLIC_URL:
        return EDITOR_PUBLIC_URL.rstrip("/")
    if not _bound_port:
        return None
    host = _bound_host
    if host in {"0.0.0.0", "::", ""}:
        host = _lan_ip()
    return f"http://{host}:{_bound_port}"


def combat_board_url(guild_id: int, scope_id: int) -> str | None:
    if not editor_is_running():
        return None
    base = editor_public_url()
    if not base:
        return None
    return f"{base.rstrip('/')}/combat/{int(guild_id)}/{int(scope_id)}"


@web.middleware
async def collapse_slashes(request: web.Request, handler):
    path = request.path
    if "//" in path:
        collapsed = "/" + "/".join(part for part in path.split("/") if part)
        if request.query_string:
            collapsed = f"{collapsed}?{request.query_string}"
        raise web.HTTPFound(collapsed)
    return await handler(request)


async def handle_editor(_request: web.Request) -> web.StreamResponse:
    if not MAP_EDITOR_FILE.is_file():
        return web.Response(status=404, text="Éditeur introuvable.")
    return web.FileResponse(
        MAP_EDITOR_FILE,
        headers={"Cache-Control": "no-store"},
    )


async def handle_health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "arkann-web"})


async def handle_combat_board(_request: web.Request) -> web.StreamResponse:
    if not COMBAT_BOARD_FILE.is_file():
        return web.Response(status=404, text="Plateau introuvable.")
    return web.FileResponse(
        COMBAT_BOARD_FILE,
        headers={"Cache-Control": "no-store"},
    )


async def handle_combat_state(request: web.Request) -> web.Response:
    try:
        guild_id = int(request.match_info["guild_id"])
        scope_id = int(request.match_info["scope_id"])
    except ValueError:
        return web.json_response({"ok": False}, status=400)
    state = get_combat(guild_id=guild_id, scope_id=scope_id)
    if state is None:
        return web.json_response({"ok": False, "empty": True}, status=404)
    payload = board_snapshot(state)
    payload["ok"] = True
    return web.json_response(payload)


def _ids(request: web.Request) -> tuple[int, int]:
    return int(request.match_info["guild_id"]), int(request.match_info["scope_id"])


async def handle_combat_action(request: web.Request) -> web.Response:
    try:
        guild_id, scope_id = _ids(request)
        payload = await request.json()
    except (ValueError, TypeError):
        return web.json_response({"ok": False, "error": "Requête invalide."}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "Requête invalide."}, status=400)
    try:
        result = await apply_web_action(guild_id, scope_id, payload)
    except ValueError as exc:
        return web.json_response(
            {"ok": False, "error": str(exc).replace("**", "")}, status=400
        )
    return web.json_response(result)


def create_app() -> web.Application:
    app = web.Application(middlewares=[collapse_slashes])
    app.router.add_get("/", handle_editor)
    app.router.add_get("/editor", handle_editor)
    app.router.add_get("/combat/{guild_id}/{scope_id}", handle_combat_board)
    app.router.add_get("/combat/{guild_id}/{scope_id}/state", handle_combat_state)
    app.router.add_post("/combat/{guild_id}/{scope_id}/action", handle_combat_action)
    app.router.add_get("/health", handle_health)
    return app


async def start_editor_server() -> str | None:
    global _runner, _bound_host, _bound_port
    if _runner is not None:
        return editor_public_url()
    if not MAP_EDITOR_FILE.is_file() and not COMBAT_BOARD_FILE.is_file():
        logger.warning("No HTML tools found in %s", TOOLS_DIR)
        return None
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, EDITOR_HOST, EDITOR_PORT)
    try:
        await site.start()
    except OSError:
        await runner.cleanup()
        logger.exception(
            "Could not bind map editor on %s:%s", EDITOR_HOST, EDITOR_PORT
        )
        return None
    sockets = getattr(getattr(site, "_server", None), "sockets", None) or []
    port = EDITOR_PORT
    if sockets:
        port = int(sockets[0].getsockname()[1])
    _runner = runner
    _bound_host = EDITOR_HOST
    _bound_port = port
    url = editor_public_url()
    logger.info("Map editor listening on %s", url)
    return url


async def stop_editor_server() -> None:
    global _runner, _bound_host, _bound_port
    runner = _runner
    _runner = None
    _bound_host = ""
    _bound_port = 0
    if runner is None:
        return
    await runner.cleanup()
