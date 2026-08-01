import pytest

from douyinks.commands import CaptureCommand, CommandParseError, DownloadCommand, parse_capture_command, parse_download_command


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


def test_parse_download_command_accepts_kuaishou_captured_count():
    assert parse_download_command("download kuaishou captured 12") == DownloadCommand(
        platform="kuaishou",
        source="captured",
        count=12,
    )


def test_parse_download_command_accepts_count_up_to_500():
    assert parse_download_command("download douyin like 500") == DownloadCommand(
        platform="douyin",
        source="like",
        count=500,
    )


def test_parse_download_command_accepts_douyin_like_range():
    assert parse_download_command("download douyin like 60-100") == DownloadCommand(
        platform="douyin",
        source="like",
        count=41,
        range_start=60,
        range_end=100,
    )


def test_parse_download_command_rejects_count_over_500():
    with pytest.raises(CommandParseError, match="count 最大为 500"):
        parse_download_command("download douyin like 501")


@pytest.mark.parametrize("message", ["download douyin like 0-10", "download douyin like 100-60", "download kuaishou like 1-10"])
def test_parse_download_command_rejects_unsupported_ranges(message):
    with pytest.raises(CommandParseError):
        parse_download_command(message)


def test_parse_capture_command_accepts_kuaishou_capture_start():
    assert parse_capture_command("  KUAISHOU CAPTURE START  ") == CaptureCommand(
        platform="kuaishou",
        target="liked",
        action="start",
    )


def test_parse_capture_command_accepts_captured_num():
    assert parse_capture_command("  CAPTURED NUM  ") == CaptureCommand(
        platform="kuaishou",
        target="liked",
        action="num",
    )


@pytest.mark.parametrize(
    "message",
    [
        "download twitter like 20",
        "download douyin bookmarks 20",
        "download douyin captured 20",
        "download douyin like 0",
        "download douyin like abc",
        "hello",
    ],
)
def test_parse_download_command_rejects_unsupported_messages(message):
    with pytest.raises(CommandParseError):
        parse_download_command(message)


@pytest.mark.parametrize("message", ["kuaishou capture stop", "douyin capture start", "captured count", "hello"])
def test_parse_capture_command_rejects_unsupported_messages(message):
    with pytest.raises(CommandParseError):
        parse_capture_command(message)
