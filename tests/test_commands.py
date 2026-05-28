import pytest

from douyinks.commands import CommandParseError, DownloadCommand, parse_download_command


def test_parse_download_command_accepts_douyin_like_count():
    assert parse_download_command("download douyin like 20") == DownloadCommand(
        platform="douyin",
        source="like",
        count=20,
    )


def test_parse_download_command_accepts_kuaishou_like_count_case_insensitive():
    assert parse_download_command("  DOWNLOAD KUAISHOU LIKE 7  ") == DownloadCommand(
        platform="kuaishou",
        source="like",
        count=7,
    )


@pytest.mark.parametrize(
    "message",
    [
        "download twitter like 20",
        "download douyin bookmarks 20",
        "download douyin like 0",
        "download douyin like abc",
        "hello",
    ],
)
def test_parse_download_command_rejects_unsupported_messages(message):
    with pytest.raises(CommandParseError):
        parse_download_command(message)
