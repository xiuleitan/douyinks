import pytest

from douyinks.config import Settings
from douyinks.downloader import DownloadService, build_daemon_command


def test_build_daemon_command_uses_configured_host_and_port():
    settings = Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": "/tmp/downloads",
            "DOUYINKS_DAEMON_HOST": "127.0.0.2",
            "DOUYINKS_DAEMON_PORT": "19999",
        }
    )

    command = build_daemon_command(settings)

    assert command[-4:] == ["--host", "127.0.0.2", "--port", "19999"]


@pytest.mark.asyncio
async def test_wait_for_extension_connection_retries_until_connected(monkeypatch):
    settings = Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": "/tmp/downloads",
        }
    )
    service = DownloadService(settings)
    statuses = [
        {"extensionConnected": False},
        {"extensionConnected": False},
        {"extensionConnected": True},
    ]
    sleep_calls = []

    async def fake_status():
        return statuses.pop(0)

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(service, "status", fake_status)
    monkeypatch.setattr("douyinks.downloader.asyncio.sleep", fake_sleep)

    await service.wait_for_extension_connection(timeout=3)

    assert sleep_calls == [1.0, 1.0]
