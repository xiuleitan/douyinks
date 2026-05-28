from ...browser import BrowserPage
from .browser_fetch import browser_fetch


async def run(page: BrowserPage, limit: int = 20, pcursor: str = "") -> list[dict]:
    await page.goto("https://www.kuaishou.com")
    await page.wait(3)

    all_items: list[dict] = []
    current_cursor = pcursor
    remaining = limit
    while remaining > 0:
        res = await browser_fetch(
            page,
            "POST",
            "https://www.kuaishou.com/rest/v/feed/liked",
            body={"pcursor": current_cursor, "page": "private"},
            headers={"referer": "https://www.kuaishou.com/"},
        )
        if not isinstance(res, dict):
            break
        feeds = res.get("feeds", [])
        if not feeds:
            break

        for item in feeds:
            photo = item.get("photo", {})
            author = item.get("author", {})
            all_items.append({
                "photo_id": photo.get("id", ""),
                "caption": photo.get("caption", ""),
                "author_name": author.get("name", ""),
                "author_id": author.get("id", ""),
                "play_url": _pick_best_url(photo),
                "timestamp": photo.get("timestamp", 0),
            })
            remaining -= 1
            if remaining <= 0:
                break

        next_cursor = res.get("pcursor", "")
        if not next_cursor or next_cursor == "no_more" or next_cursor == current_cursor:
            break
        current_cursor = next_cursor

    return all_items[:limit]


def _pick_best_url(photo: dict) -> str:
    h265_urls = photo.get("photoH265Urls", [])
    if h265_urls and isinstance(h265_urls, list) and h265_urls[0].get("url"):
        return h265_urls[0]["url"]
    photo_urls = photo.get("photoUrls", [])
    if photo_urls and isinstance(photo_urls, list) and photo_urls[0].get("url"):
        return photo_urls[0]["url"]
    manifest = photo.get("manifest", {})
    if isinstance(manifest, dict):
        adaptation_sets = manifest.get("adaptationSet", [])
        if adaptation_sets:
            representations = adaptation_sets[0].get("representation", [])
            if representations and representations[0].get("url"):
                return representations[0]["url"]
    return ""
