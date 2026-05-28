from douyinks.config import Settings


def test_settings_from_env_parses_required_values_and_defaults():
    settings = Settings.from_mapping(
        {
            "MATRIX_HOMESERVER_URL": "https://matrix.example",
            "MATRIX_USERNAME": "@bot:example",
            "MATRIX_PASSWORD": "secret",
            "MATRIX_ALLOWED_ROOM_IDS": "!a:example, !b:example",
            "DOWNLOAD_ROOT": "/tmp/downloads",
        }
    )

    assert settings.matrix_homeserver_url == "https://matrix.example"
    assert settings.matrix_allowed_room_ids == {"!a:example", "!b:example"}
    assert settings.download_root == "/tmp/downloads"
    assert settings.daemon_port == 19826
    assert settings.douyin_likes_dir.endswith("/douyin/likes")
    assert settings.kuaishou_likes_dir.endswith("/kuaishou/likes")
    assert settings.matrix_sync_state_path.endswith("/matrix_sync_state.json")


def test_settings_from_env_reports_missing_required_values():
    errors = Settings.validate_mapping({})

    assert "MATRIX_HOMESERVER_URL" in errors
    assert "MATRIX_USERNAME" in errors
    assert "MATRIX_PASSWORD" in errors
    assert "MATRIX_ALLOWED_ROOM_IDS" in errors
    assert "DOWNLOAD_ROOT" in errors
