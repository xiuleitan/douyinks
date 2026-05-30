import asyncio
import logging
from urllib.parse import quote

from aiohttp import web

from .config import Settings
from .sync_transfer import SyncTransferState


logger = logging.getLogger(__name__)
SETTINGS_KEY = web.AppKey("settings", Settings)


def create_sync_app(settings: Settings) -> web.Application:
    SyncTransferState(settings.sync_state_path).initialize_baseline(settings.download_history_path)
    app = web.Application()
    app[SETTINGS_KEY] = settings
    app.router.add_get("/sync/health", health)
    app.router.add_get("/sync/pending", pending)
    app.router.add_get(r"/sync/files/{file_id:.+}", file)
    app.router.add_post("/sync/ack", ack)
    return app


async def health(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "service": "douyinks-sync",
            "version": 1,
        }
    )


async def pending(request: web.Request) -> web.Response:
    settings = _authorized_settings(request)
    state = SyncTransferState(settings.sync_state_path)
    files = state.pending_from_history(settings.download_history_path)
    for item in files:
        item["download_url"] = f"/sync/files/{quote(item['id'], safe='')}"
    return web.json_response({"files": files})


async def file(request: web.Request) -> web.StreamResponse:
    settings = _authorized_settings(request)
    file_id = request.match_info["file_id"]
    state = SyncTransferState(settings.sync_state_path)
    file_path = state.file_path_from_history(settings.download_history_path, file_id)
    if not file_path:
        raise web.HTTPNotFound(text="file not found")
    return web.FileResponse(path=file_path)


async def ack(request: web.Request) -> web.Response:
    settings = _authorized_settings(request)
    try:
        payload = await request.json()
    except Exception as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    file_ids = payload.get("file_ids")
    if not isinstance(file_ids, list) or not all(isinstance(item, str) for item in file_ids):
        raise web.HTTPBadRequest(text="file_ids must be a list of strings")
    device_id = payload.get("device_id", "")
    if not isinstance(device_id, str):
        raise web.HTTPBadRequest(text="device_id must be a string")
    state = SyncTransferState(settings.sync_state_path)
    synced = state.mark_synced(file_ids, device_id=device_id)
    return web.json_response({"ok": True, "synced": synced})


async def start_sync_server(settings: Settings) -> None:
    if not settings.sync_token:
        raise RuntimeError("SYNC_TOKEN is required before starting the sync server")
    app = create_sync_app(settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.sync_server_host, settings.sync_server_port)
    await site.start()
    logger.info(
        "Douyinks sync server listening on http://%s:%s",
        settings.sync_server_host,
        settings.sync_server_port,
    )
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def run_sync_server(settings: Settings) -> None:
    asyncio.run(start_sync_server(settings))


def _authorized_settings(request: web.Request) -> Settings:
    settings: Settings = request.app[SETTINGS_KEY]
    expected = f"Bearer {settings.sync_token}"
    if not settings.sync_token or request.headers.get("Authorization") != expected:
        raise web.HTTPUnauthorized(text="missing or invalid sync token")
    return settings
