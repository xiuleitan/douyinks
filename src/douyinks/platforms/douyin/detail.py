import re
from urllib.parse import urlencode

from ...browser import BrowserPage
from .browser_fetch import browser_fetch


def extract_aweme_id(input_str: str) -> str:
    input_str = input_str.strip()
    if input_str.isdigit():
        return input_str
    match = re.search(r"/(?:video|note)/(\d+)", input_str)
    if match:
        return match.group(1)
    raise ValueError(f"无法从输入中提取视频编号: {input_str}")


async def run(page: BrowserPage, aweme_id: str) -> list[dict]:
    params = urlencode({"device_platform": "webapp", "aid": "6383", "aweme_id": aweme_id})
    url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/?{params}"
    res = await browser_fetch(page, "GET", url, headers={"referer": "https://www.douyin.com/"})
    if not isinstance(res, dict):
        raise RuntimeError("获取视频详情失败: 响应格式异常")
    detail = res.get("aweme_detail")
    if not detail:
        raise RuntimeError(f"视频不存在或已删除: {aweme_id}")
    is_note = _is_note_detail(detail)
    play_urls = detail.get("video", {}).get("play_addr", {}).get("url_list", [])
    image_urls = _extract_image_urls(detail, include_video_images=is_note)
    child_video_urls = _extract_child_video_urls(detail)
    if is_note and (image_urls or child_video_urls):
        play_urls = []
    if not play_urls and not image_urls and not child_video_urls:
        dom_media = await _extract_note_dom_media(page, detail.get("aweme_id", aweme_id))
        child_video_urls = dom_media["video_urls"]
        image_urls = dom_media["image_urls"]
    media_type = _media_type(play_urls, image_urls, child_video_urls)
    return [{
        "aweme_id": detail.get("aweme_id", aweme_id),
        "desc": detail.get("desc", ""),
        "author": detail.get("author", {}).get("nickname", ""),
        "author_douyin_id": detail.get("author", {}).get("unique_id", ""),
        "create_time": detail.get("create_time", 0),
        "media_type": media_type,
        "play_url": play_urls[0] if play_urls else "",
        "image_urls": image_urls,
        "video_urls": child_video_urls,
    }]


def _extract_image_urls(detail: dict, *, include_video_images: bool = False) -> list[str]:
    urls: list[str] = []
    for image in detail.get("images", []) or []:
        if not isinstance(image, dict):
            continue
        if not include_video_images and _extract_image_video_urls(image):
            continue
        candidates = image.get("url_list") or image.get("download_url_list") or []
        if not candidates and isinstance(image.get("uri"), str):
            candidates = [image["uri"]]
        if candidates:
            urls.append(str(candidates[0]))
    return urls


def _extract_child_video_urls(detail: dict) -> list[str]:
    urls: list[str] = []
    for image in detail.get("images", []) or []:
        if not isinstance(image, dict):
            continue
        urls.extend(_extract_image_video_urls(image))
    return _dedupe(urls)


def _extract_image_video_urls(image: dict) -> list[str]:
    urls: list[str] = []
    for key in ("video", "video_info"):
        nested = image.get(key)
        if isinstance(nested, dict):
            urls.extend(_extract_play_urls(nested))
    urls.extend(_extract_play_urls(image))
    return _dedupe(urls)


def _extract_play_urls(obj: dict) -> list[str]:
    play_addr = obj.get("play_addr")
    if isinstance(play_addr, dict):
        url = _first_url(play_addr.get("url_list", []))
        if url:
            return [url]
    bit_rate = obj.get("bit_rate")
    if isinstance(bit_rate, list):
        for item in bit_rate:
            if isinstance(item, dict):
                urls = _extract_play_urls(item)
                if urls:
                    return urls
    return []


def _first_url(values: list) -> str:
    for value in values:
        if value:
            return str(value)
    return ""


async def _extract_note_dom_media(page: BrowserPage, aweme_id: str) -> dict[str, list[str]]:
    await page.goto(f"https://www.douyin.com/note/{aweme_id}")
    await page.wait(3)
    result = await page.evaluate(NOTE_DOM_MEDIA_JS)
    if not isinstance(result, dict):
        return {"video_urls": [], "image_urls": []}
    return {
        "video_urls": _dedupe([str(url) for url in result.get("video_urls", []) if url]),
        "image_urls": _dedupe([str(url) for url in result.get("image_urls", []) if url]),
    }


def _media_type(play_urls: list[str], image_urls: list[str], child_video_urls: list[str]) -> str:
    if play_urls:
        return "video"
    if child_video_urls and image_urls:
        return "mixed"
    if child_video_urls:
        return "mixed"
    if image_urls:
        return "image"
    return "unknown"


def _is_note_detail(detail: dict) -> bool:
    if detail.get("aweme_type") == 68:
        return True
    share_url = detail.get("share_info", {}).get("share_url", "")
    return isinstance(share_url, str) and "/share/slides/" in share_url


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


NOTE_DOM_MEDIA_JS = """
(() => {
  const videoUrls = [];
  const imageUrls = [];
  document.querySelectorAll('video source[src], video[src]').forEach((el) => {
    const src = el.src || el.getAttribute('src');
    if (src) videoUrls.push(src);
  });
  document.querySelectorAll('img[src]').forEach((img) => {
    const src = img.src || img.getAttribute('src');
    if (src && src.includes('douyinpic.com')) imageUrls.push(src);
  });
  return {
    video_urls: Array.from(new Set(videoUrls)),
    image_urls: Array.from(new Set(imageUrls)),
  };
})()
"""
