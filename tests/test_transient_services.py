import asyncio
import sys

import pytest

from douyinks.config import Settings
from douyinks.transient_services import TransientRuntimeServices, build_sync_server_command


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited = True


def make_settings(tmp_path, *, sync_enabled=True):
    return Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": str(tmp_path),
            "DOUYINKS_DAEMON_HOST": "127.0.0.1",
            "DOUYINKS_DAEMON_PORT": "19826",
            "SYNC_SERVER_ENABLED": "true" if sync_enabled else "false",
            "SYNC_SERVER_HOST": "0.0.0.0",
            "SYNC_SERVER_PORT": "19827",
            "SYNC_TOKEN": "test-sync-token",
        }
    )


def test_build_sync_server_command_uses_configured_host_port_and_log_level(tmp_path):
    settings = make_settings(tmp_path)

    assert build_sync_server_command(settings, "DEBUG") == [
        sys.executable,
        "-m",
        "douyinks",
        "sync-server",
        "--host",
        "0.0.0.0",
        "--port",
        "19827",
        "--log-level",
        "DEBUG",
    ]


@pytest.mark.asyncio
async def test_transient_services_start_daemon_and_sync_server_then_stop_after_idle(tmp_path):
    settings = make_settings(tmp_path)
    launched = []
    processes = []

    async def check_daemon(_host, _port):
        return any(name == "daemon" for name, _ in launched)

    async def check_sync(_settings):
        return any(name == "sync-server" for name, _ in launched)

    def popen(command, **_kwargs):
        process = FakeProcess()
        processes.append(process)
        name = "sync-server" if "sync-server" in command else "daemon"
        launched.append((name, command))
        return process

    services = TransientRuntimeServices(
        settings,
        idle_seconds=0.01,
        check_daemon_func=check_daemon,
        check_sync_server_func=check_sync,
        popen=popen,
    )

    await services.start_for_download()
    services.schedule_idle_stop()
    await asyncio.sleep(0.05)

    assert [name for name, _ in launched] == ["daemon", "sync-server"]
    assert all(process.terminated for process in processes)


@pytest.mark.asyncio
async def test_transient_services_do_not_stop_manually_running_daemon(tmp_path):
    settings = make_settings(tmp_path, sync_enabled=False)
    launched = []

    async def check_daemon(_host, _port):
        return True

    def popen(command, **_kwargs):
        launched.append(command)
        return FakeProcess()

    services = TransientRuntimeServices(
        settings,
        idle_seconds=0.01,
        check_daemon_func=check_daemon,
        popen=popen,
    )

    await services.start_for_download()
    services.schedule_idle_stop()
    await asyncio.sleep(0.05)

    assert launched == []
