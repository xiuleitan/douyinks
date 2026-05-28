from dataclasses import dataclass


class CommandParseError(ValueError):
    """Raised when a Matrix text message is not a supported download command."""


@dataclass(frozen=True)
class DownloadCommand:
    platform: str
    source: str
    count: int


def parse_download_command(message: str) -> DownloadCommand:
    parts = message.strip().lower().split()
    if len(parts) != 4 or parts[0] != "download":
        raise CommandParseError("用法: download <douyin|kuaishou> like <count>")

    _, platform, source, count_text = parts
    if platform not in {"douyin", "kuaishou"}:
        raise CommandParseError("仅支持平台: douyin, kuaishou")
    if source != "like":
        raise CommandParseError("v1 仅支持 source: like")

    try:
        count = int(count_text)
    except ValueError as exc:
        raise CommandParseError("count 必须是正整数") from exc

    if count <= 0:
        raise CommandParseError("count 必须是正整数")
    if count > 200:
        raise CommandParseError("count 最大为 200")

    return DownloadCommand(platform=platform, source=source, count=count)
