import pytest

from douyinks.commands import DownloadCommand


@pytest.mark.parametrize("platform,source", [("douyin", "like"), ("kuaishou", "like"), ("kuaishou", "captured")])
def test_download_command_accepts_count(platform, source):
    command = DownloadCommand(platform, source, 300)
    assert command.count == 300


@pytest.mark.parametrize("count", [0, -1, 501])
def test_download_command_rejects_invalid_count(count):
    with pytest.raises(ValueError, match="下载数量"):
        DownloadCommand("douyin", "like", count)


def test_download_command_preserves_douyin_range():
    assert DownloadCommand("douyin", "like", 41, 60, 100).range_end == 100


@pytest.mark.parametrize("platform,source,start,end", [
    ("other", "like", None, None),
    ("douyin", "captured", None, None),
    ("kuaishou", "unknown", None, None),
    ("kuaishou", "captured", 1, 2),
    ("douyin", "like", None, 2),
    ("douyin", "like", 0, 1),
    ("douyin", "like", 1, 3),
])
def test_download_command_rejects_unsupported_requests(platform, source, start, end):
    with pytest.raises(ValueError):
        DownloadCommand(platform, source, 2, start, end)
