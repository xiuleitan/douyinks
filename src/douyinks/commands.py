from dataclasses import dataclass


MAX_DOWNLOAD_COUNT = 500


@dataclass(frozen=True)
class DownloadCommand:
    platform: str
    source: str
    count: int
    range_start: int | None = None
    range_end: int | None = None

    def __post_init__(self):
        if self.platform not in {"douyin", "kuaishou"}:
            raise ValueError("仅支持平台: douyin, kuaishou")
        if self.source not in {"like", "captured"}:
            raise ValueError("仅支持 source: like, captured")
        if self.source == "captured" and self.platform != "kuaishou":
            raise ValueError("captured 仅支持 kuaishou")
        if not 1 <= self.count <= MAX_DOWNLOAD_COUNT:
            raise ValueError(f"下载数量必须是 1–{MAX_DOWNLOAD_COUNT} 的整数")
        if self.range_start is None and self.range_end is None:
            return
        if self.platform != "douyin" or self.source != "like":
            raise ValueError("范围下载仅支持 douyin like")
        if self.range_start is None or self.range_end is None:
            raise ValueError("范围需要同时指定起点和终点")
        if self.range_start < 1 or self.range_end - self.range_start + 1 != self.count:
            raise ValueError("范围必须与下载数量一致，起点必须为正整数")
