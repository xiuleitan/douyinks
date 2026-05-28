from douyinks.config import Settings
from douyinks.downloader import build_daemon_command


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
