import sys

from click.testing import CliRunner

import douyinks.main as main_module
from douyinks.config import Settings
from douyinks.main import cli
from douyinks.supervisor import build_service_commands


def make_settings(tmp_path):
    return Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!allowed:example",
            "DOWNLOAD_ROOT": str(tmp_path),
            "DOUYINKS_DAEMON_HOST": "127.0.0.1",
            "DOUYINKS_DAEMON_PORT": "19826",
            "SYNC_SERVER_HOST": "0.0.0.0",
            "SYNC_SERVER_PORT": "19827",
            "SYNC_TOKEN": "test-sync-token",
        }
    )


def test_build_service_commands_starts_daemon_bot_and_sync_server(tmp_path):
    settings = make_settings(tmp_path)

    commands = build_service_commands(settings, log_level="DEBUG")

    assert commands == [
        (
            "daemon",
            [
                sys.executable,
                "-m",
                "douyinks",
                "daemon",
                "--host",
                "127.0.0.1",
                "--port",
                "19826",
            ],
        ),
        ("bot", [sys.executable, "-m", "douyinks", "bot", "--log-level", "DEBUG"]),
        (
            "sync-server",
            [
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
            ],
        ),
    ]


def test_serve_command_loads_settings_and_runs_supervisor(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    calls = []
    monkeypatch.setattr(main_module.Settings, "load", lambda: settings)
    monkeypatch.setattr(main_module, "supervise_services", lambda commands: calls.append(commands))

    result = CliRunner().invoke(cli, ["serve", "--log-level", "WARNING"])

    assert result.exit_code == 0
    assert calls == [build_service_commands(settings, log_level="WARNING")]
