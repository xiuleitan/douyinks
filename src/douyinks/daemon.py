import asyncio
import json
import logging
import signal
import sys
from typing import Any

from aiohttp import WSMsgType, web

from .config import CUSTOM_HEADER, DAEMON_IDLE_TIMEOUT, DEFAULT_DAEMON_HOST, DEFAULT_DAEMON_PORT

logger = logging.getLogger("douyinks.daemon")
extension_ws: web.WebSocketResponse | None = None
extension_version: str | None = None
pending: dict[str, asyncio.Future] = {}
idle_handle: asyncio.TimerHandle | None = None
MAX_BODY = 1024 * 1024


def reset_idle_timer(loop: asyncio.AbstractEventLoop) -> None:
    global idle_handle
    if idle_handle:
        idle_handle.cancel()
    idle_handle = loop.call_later(DAEMON_IDLE_TIMEOUT, _idle_shutdown)


def _idle_shutdown() -> None:
    logger.info("Idle timeout, shutting down")
    sys.exit(0)


def check_origin(request: web.Request) -> str | None:
    origin = request.headers.get("Origin")
    if origin and not origin.startswith("chrome-extension://"):
        return "Forbidden: cross-origin request blocked"
    return None


def check_custom_header(request: web.Request) -> str | None:
    if CUSTOM_HEADER not in request.headers:
        return f"Forbidden: missing {CUSTOM_HEADER} header"
    return None


async def handle_ping(request: web.Request) -> web.Response:
    origin_err = check_origin(request)
    if origin_err:
        return web.json_response({"ok": False, "error": origin_err}, status=403)
    return web.json_response({"ok": True})


async def handle_status(request: web.Request) -> web.Response:
    origin_err = check_origin(request)
    if origin_err:
        return web.json_response({"ok": False, "error": origin_err}, status=403)
    header_err = check_custom_header(request)
    if header_err:
        return web.json_response({"ok": False, "error": header_err}, status=403)
    return web.json_response({
        "ok": True,
        "extensionConnected": extension_ws is not None and not extension_ws.closed,
        "extensionVersion": extension_version,
        "pending": len(pending),
    })


async def handle_command(request: web.Request) -> web.Response:
    global extension_ws
    origin_err = check_origin(request)
    if origin_err:
        return web.json_response({"ok": False, "error": origin_err}, status=403)
    header_err = check_custom_header(request)
    if header_err:
        return web.json_response({"ok": False, "error": header_err}, status=403)
    reset_idle_timer(asyncio.get_running_loop())

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    cmd_id = body.get("id")
    if not cmd_id:
        return web.json_response({"ok": False, "error": "Missing command id"}, status=400)
    if extension_ws is None or extension_ws.closed:
        return web.json_response(
            {"id": cmd_id, "ok": False, "error": "Extension not connected. Load the Douyinks Browser Bridge extension."},
            status=503,
        )

    timeout_s = body.get("timeout", 120)
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        timeout_s = 120

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    pending[cmd_id] = future
    try:
        await extension_ws.send_json(body)
        result = await asyncio.wait_for(future, timeout=timeout_s)
        return web.json_response(result)
    except asyncio.TimeoutError:
        pending.pop(cmd_id, None)
        return web.json_response({"id": cmd_id, "ok": False, "error": f"Command timeout ({timeout_s}s)"}, status=408)
    except Exception as exc:
        pending.pop(cmd_id, None)
        return web.json_response({"id": cmd_id, "ok": False, "error": str(exc)}, status=400)


async def handle_ext_ws(request: web.Request) -> web.WebSocketResponse:
    global extension_ws, extension_version
    origin = request.headers.get("Origin", "")
    if origin and not origin.startswith("chrome-extension://"):
        raise web.HTTPForbidden(text="Forbidden: cross-origin WebSocket blocked")

    ws = web.WebSocketResponse(heartbeat=15.0)
    await ws.prepare(request)
    logger.info("Extension connected")
    extension_ws = ws
    extension_version = None

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "hello":
                    extension_version = data.get("version")
                    continue
                if data.get("type") == "log":
                    getattr(logger, data.get("level", "info"), logger.info)(f"[ext] {data.get('msg', '')}")
                    continue
                cmd_id = data.get("id")
                if cmd_id and cmd_id in pending:
                    future = pending.pop(cmd_id)
                    if not future.done():
                        future.set_result(data)
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        logger.info("Extension disconnected")
        if extension_ws is ws:
            extension_ws = None
            extension_version = None
            for future in pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("Extension disconnected"))
            pending.clear()
    return ws


def create_app() -> web.Application:
    app = web.Application(client_max_size=MAX_BODY)
    app.router.add_get("/ping", handle_ping)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/command", handle_command)
    app.router.add_get("/ext", handle_ext_ws)
    return app


def main(host: str = DEFAULT_DAEMON_HOST, port: int = DEFAULT_DAEMON_PORT) -> None:
    logging.basicConfig(level=logging.INFO, format="[douyinks-daemon] %(message)s", stream=sys.stderr)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    reset_idle_timer(loop)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    logger.info(f"Listening on http://{host}:{port}")
    web.run_app(create_app(), host=host, port=port, print=None)


if __name__ == "__main__":
    main()
