import os
from pathlib import Path

import pytest

import douyinks.config as config
from douyinks.config import Settings


def test_settings_need_no_credentials_or_required_environment():
    settings = Settings.from_mapping({})
    assert settings.download_root == str(Path("~/Downloads/douyinks").expanduser().resolve())
    assert settings.daemon_host == "127.0.0.1"
    assert settings.daemon_port == 19826
    assert settings.download_delay_seconds == 3
    assert settings.douyin_likes_dir.endswith("/douyin/likes")
    assert settings.kuaishou_likes_dir.endswith("/kuaishou/likes")


def test_settings_parse_local_options(tmp_path):
    settings = Settings.from_mapping({
        "DOWNLOAD_ROOT": str(tmp_path),
        "DOUYINKS_DAEMON_HOST": "127.0.0.2",
        "DOUYINKS_DAEMON_PORT": "19999",
        "DOWNLOAD_DELAY_SECONDS": "0.5",
    })
    assert settings.download_root == str(tmp_path)
    assert settings.daemon_host == "127.0.0.2"
    assert settings.daemon_port == 19999
    assert settings.download_delay_seconds == 0.5


@pytest.mark.parametrize("key,value", [
    ("DOUYINKS_DAEMON_PORT", "0"),
    ("DOUYINKS_DAEMON_PORT", "65536"),
    ("DOUYINKS_DAEMON_PORT", "abc"),
    ("DOWNLOAD_DELAY_SECONDS", "-1"),
    ("DOWNLOAD_DELAY_SECONDS", "nan"),
    ("DOWNLOAD_DELAY_SECONDS", "inf"),
    ("DOWNLOAD_DELAY_SECONDS", "abc"),
])
def test_settings_report_invalid_local_options(key, value):
    with pytest.raises(ValueError, match=key):
        Settings.from_mapping({key: value})


def test_load_uses_project_env_from_another_directory_without_changing_process_env(tmp_path, monkeypatch):
    project = tmp_path / "project"
    source = project / "src" / "douyinks"
    source.mkdir(parents=True)
    (project / "pyproject.toml").touch()
    (project / ".env").write_text("DOWNLOAD_ROOT=videos\nDOUYINKS_DAEMON_PORT=19999\n")
    other = tmp_path / "other"
    other.mkdir()
    (other / ".env").write_text("DOWNLOAD_ROOT=wrong-directory\n")
    for key in ("DOUYINKS_ENV_FILE", "DOWNLOAD_ROOT", "DOUYINKS_DAEMON_PORT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "__file__", str(source / "config.py"))
    monkeypatch.chdir(other)

    settings = Settings.load()

    assert settings.download_root == str(project / "videos")
    assert settings.daemon_port == 19999
    assert "DOWNLOAD_ROOT" not in os.environ


def test_load_honors_explicit_env_file_and_environment_override(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    env_file.write_text("DOWNLOAD_ROOT=local-videos\nDOUYINKS_DAEMON_PORT=19999\n")
    monkeypatch.delenv("DOWNLOAD_ROOT", raising=False)
    monkeypatch.setenv("DOUYINKS_DAEMON_PORT", "20000")
    monkeypatch.setenv("DOUYINKS_ENV_FILE", str(env_file))

    settings = Settings.load()

    assert settings.download_root == str(tmp_path / "local-videos")
    assert settings.daemon_port == 20000
    assert Settings.load(env_file) == settings
