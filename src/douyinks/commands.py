from dataclasses import dataclass


MAX_DOWNLOAD_COUNT = 500


class CommandParseError(ValueError):
    """Raised when a Matrix text message is not a supported download command."""


@dataclass(frozen=True)
class DownloadCommand:
    platform: str
    source: str
    count: int
    range_start: int | None = None
    range_end: int | None = None


@dataclass(frozen=True)
class CaptureCommand:
    platform: str
    target: str
    action: str


def parse_download_command(message: str) -> DownloadCommand:
    parts = message.strip().lower().split()
    if len(parts) != 4 or parts[0] != "download":
        raise CommandParseError("用法: download <douyin|kuaishou> <like|captured> <count>")

    _, platform, source, count_text = parts
    if platform not in {"douyin", "kuaishou"}:
        raise CommandParseError("仅支持平台: douyin, kuaishou")
    if source not in {"like", "captured"}:
        raise CommandParseError("仅支持 source: like, captured")
    if source == "captured" and platform != "kuaishou":
        raise CommandParseError("captured 目前仅支持 kuaishou")

    if "-" in count_text:
        if platform != "douyin" or source != "like":
            raise CommandParseError("范围下载目前仅支持 douyin like")
        start, end = _parse_range(count_text)
        return DownloadCommand(platform=platform, source=source, count=end - start + 1, range_start=start, range_end=end)

    count = _parse_positive_int(count_text)

    if count <= 0:
        raise CommandParseError("count 必须是正整数")
    if count > MAX_DOWNLOAD_COUNT:
        raise CommandParseError(f"count 最大为 {MAX_DOWNLOAD_COUNT}")

    return DownloadCommand(platform=platform, source=source, count=count)


def _parse_positive_int(text: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise CommandParseError("count 必须是正整数") from exc


def _parse_range(text: str) -> tuple[int, int]:
    parts = text.split("-", 1)
    if len(parts) != 2:
        raise CommandParseError("范围格式应为 start-end")
    start = _parse_positive_int(parts[0])
    end = _parse_positive_int(parts[1])
    if start <= 0 or end <= 0:
        raise CommandParseError("范围必须是正整数")
    if start > end:
        raise CommandParseError("范围起点不能大于终点")
    if end > MAX_DOWNLOAD_COUNT:
        raise CommandParseError(f"count 最大为 {MAX_DOWNLOAD_COUNT}")
    return start, end


def parse_capture_command(message: str) -> CaptureCommand:
    parts = message.strip().lower().split()
    if parts == ["kuaishou", "capture", "start"]:
        return CaptureCommand(platform="kuaishou", target="liked", action="start")
    if parts == ["captured", "num"]:
        return CaptureCommand(platform="kuaishou", target="liked", action="num")
    raise CommandParseError("用法: kuaishou capture start 或 captured num")
