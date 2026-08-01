from typing import Any

from ...browser import BrowserPage
from .browser_fetch import KuaishouAPIError


HOME_URL = "https://www.kuaishou.com"
LIKED_API_URL = "https://www.kuaishou.com/rest/v/feed/liked?caver=2"
CAPTURE_SETTLE_POLL_SECONDS = 0.2
CAPTURE_SETTLE_POLLS = 50
LIKED_RESPONSE_HOOK = r"""
(() => {
  if (window.__douyinksKuaishouLikedHookInstalled) return true;
  window.__douyinksKuaishouLikedHookInstalled = true;
  window.__douyinksKuaishouLikedResponses = [];

  const pushLikedResponse = (url, data) => {
    if (!url || !String(url).includes('/rest/v/feed/liked')) return;
    window.__douyinksKuaishouLikedResponses.push({ url: String(url), data, ts: Date.now() });
  };

  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    try {
      const rawUrl = typeof args[0] === 'string' ? args[0] : args[0]?.url;
      if (rawUrl && String(rawUrl).includes('/rest/v/feed/liked')) {
        response.clone().json().then((data) => pushLikedResponse(rawUrl, data)).catch(() => {});
      }
    } catch (_) {}
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this.__douyinksKuaishouUrl = url;
    return originalOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function(...args) {
    this.addEventListener('loadend', function() {
      try {
        const rawUrl = this.__douyinksKuaishouUrl;
        if (rawUrl && String(rawUrl).includes('/rest/v/feed/liked')) {
          pushLikedResponse(rawUrl, JSON.parse(this.responseText));
        }
      } catch (_) {}
    });
    return originalSend.apply(this, args);
  };

  return true;
})()
"""
OPEN_LIKED_TAB_SCRIPT = r"""
(() => {
  window.__douyinksKuaishouLikedResponses = [];
  function normalizeText(node) {
    return String(node?.textContent || node?.innerText || '').replace(/\s+/g, '');
  }
  function candidateNodes() {
    const selectors = [
      '.tab-nav [role="button"]',
      '.tab-nav .tab-item',
      '.tab-container [role="button"]',
      '.tab-container .tab-item',
      '[role="button"]',
      '.tab-item',
      'button',
      'a',
      'div',
      'span',
    ];
    const seen = new Set();
    const nodes = [];
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        if (seen.has(node)) continue;
        seen.add(node);
        nodes.push(node);
      }
    }
    return nodes;
  }
  function visibleEnough(node) {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || 1) > 0;
  }
  function findLikedTab() {
    const nodes = candidateNodes();
    const matches = nodes
      .map((node) => {
        const text = normalizeText(node);
        const clickable = node.closest('[role="button"], button, a, span, div') || node;
        return { node, clickable, text };
      })
      .filter((item) => {
        if (!visibleEnough(item.clickable)) return false;
        if (!item.text || item.text.length > 20) return false;
        if (item.text.includes('获赞')) return false;
        return item.text === '点赞' || item.text.startsWith('点赞') || item.text.includes('点赞');
      })
      .sort((a, b) => {
        const ar = a.clickable.getBoundingClientRect();
        const br = b.clickable.getBoundingClientRect();
        return (ar.top - br.top) || (ar.left - br.left);
      });
    return matches[0] || null;
  }
  function activeTabText() {
    const activeNodes = Array.from(document.querySelectorAll('.tab-item-active, .is-active, [aria-selected="true"]'))
      .filter((node) => visibleEnough(node));
    return activeNodes.map((node) => normalizeText(node)).join('|');
  }
  function __douyinksKuaishouOpenLikedTab() {
    const active = activeTabText();
    if (active.includes('点赞') && !active.includes('获赞')) {
      return { ok: true, alreadyActive: true, tabs: collectTabTexts() };
    }
    const match = findLikedTab();
    if (!match) return { ok: false, tabs: collectTabTexts() };
    match.clickable.scrollIntoView({ block: 'center', inline: 'center' });
    const rect = match.clickable.getBoundingClientRect();
    return {
      ok: true,
      clickedText: match.text,
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      tabs: collectTabTexts(),
    };
  }
  function collectTabTexts() {
    return candidateNodes()
      .filter((node) => visibleEnough(node))
      .map((node) => normalizeText(node))
      .filter(Boolean)
      .filter((text) => text.length <= 20)
      .filter((text) => text.includes('作品') || text.includes('点赞') || text.includes('收藏') || text.includes('私密') || text.includes('获赞'))
      .slice(0, 40);
  }
  return __douyinksKuaishouOpenLikedTab();
})()
"""
OPEN_WORKS_TAB_SCRIPT = r"""
(() => {
  function normalizeText(node) {
    return String(node?.textContent || node?.innerText || '').replace(/\s+/g, '');
  }
  function visibleEnough(node) {
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || 1) > 0;
  }
  function __douyinksKuaishouOpenWorksTab() {
    const selectors = ['.tab-nav [role="button"]', '.tab-nav .tab-item', '.tab-container [role="button"]', '.tab-container .tab-item'];
    for (const selector of selectors) {
      for (const node of document.querySelectorAll(selector)) {
        const text = normalizeText(node);
        if (text !== '作品' || !visibleEnough(node)) continue;
        node.scrollIntoView({ block: 'center', inline: 'center' });
        const rect = node.getBoundingClientRect();
        return {
          ok: true,
          clickedText: text,
          x: rect.left + rect.width / 2,
          y: rect.top + rect.height / 2,
        };
      }
    }
    return { ok: false };
  }
  return __douyinksKuaishouOpenWorksTab();
})()
"""


async def run(page: BrowserPage, limit: int = 20, pcursor: str = "") -> list[dict]:
    await _open_liked_page(page)
    return await _collect_liked_videos_via_api(page, limit=limit, pcursor=pcursor)


async def start_capture(page: BrowserPage) -> dict[str, Any]:
    result = await page.start_kuaishou_liked_capture()
    return result if isinstance(result, dict) else {}


async def read_captured(page: BrowserPage, limit: int = 20) -> list[dict]:
    summary = await _wait_for_captured_responses(page, limit=limit)
    pending = summary["pending_response_count"]
    if pending:
        raise KuaishouAPIError(f"快手 liked 仍有 {pending} 条响应未完成，请稍后再发送下载指令。")
    if summary["error_count"]:
        raise KuaishouAPIError(
            f"快手 liked 有 {summary['error_count']} 条响应读取失败；为避免漏下载，未开始下载，请重新开始捕获后再试。"
        )
    if summary["dropped_response_count"]:
        raise KuaishouAPIError(
            f"快手 liked 有 {summary['dropped_response_count']} 条响应超出缓存上限；为避免漏下载，未开始下载，请重新开始捕获后再试。"
        )
    videos = summary["videos"]
    if not videos:
        raise KuaishouAPIError("尚未捕获到快手 liked 响应，请先发送 kuaishou capture start，然后在快手页面刷新/滚动。")
    return videos


async def _wait_for_captured_responses(page: BrowserPage, *, limit: int) -> dict[str, Any]:
    for _ in range(CAPTURE_SETTLE_POLLS):
        summary = await captured_summary(page, limit=limit)
        if summary["pending_response_count"] == 0:
            return summary
        await page.wait(CAPTURE_SETTLE_POLL_SECONDS)
    return await captured_summary(page, limit=limit)


async def captured_summary(page: BrowserPage, limit: int = 10000) -> dict[str, Any]:
    result = await page.read_kuaishou_liked_capture()
    if not isinstance(result, dict):
        raise KuaishouAPIError("未能读取快手 liked 捕获结果。")
    responses = _captured_response_data(result)
    videos = _extract_liked_videos_from_responses(responses, limit=limit)
    errors = result.get("errors", [])
    response_count = len(responses)
    return {
        "videos": videos,
        "video_count": len(videos),
        "response_count": response_count,
        "matched_response_count": _capture_count(result, "matched", response_count),
        "completed_response_count": _capture_count(result, "completed", response_count),
        "error_count": _capture_count(result, "failed", len(errors) if isinstance(errors, list) else 0),
        "pending_response_count": _capture_count(result, "pending", 0),
        "dropped_response_count": _capture_count(result, "dropped", 0),
    }


def _captured_response_data(result: dict[str, Any]) -> list[dict[str, Any]]:
    responses = []
    for item in result.get("responses", []):
        if isinstance(item, dict) and isinstance(item.get("data"), dict):
            responses.append(item["data"])
    return responses


def _capture_count(result: dict[str, Any], key: str, default: int) -> int:
    value = result.get(key, default)
    return value if isinstance(value, int) and value >= 0 else default


async def _open_liked_page(page: BrowserPage) -> None:
    await page.goto(HOME_URL)
    await page.wait(3)
    profile_url = await _find_profile_url(page)
    if profile_url:
        await page.goto(profile_url)
        await page.wait(3)
        return

    clicked = await page.evaluate("""
    (() => {
      const nodes = Array.from(document.querySelectorAll('a, button, div, span'));
      const target = nodes.find((node) => (node.innerText || '').trim() === '我的');
      if (!target) return false;
      target.click();
      return true;
    })()
    """)
    if not clicked:
        raise KuaishouAPIError("无法定位快手个人主页，请确认 Chrome 已登录快手。")
    await page.wait(3)


async def _collect_liked_videos_via_api(page: BrowserPage, *, limit: int, pcursor: str = "") -> list[dict]:
    videos: list[dict] = []
    seen: set[str] = set()
    current_cursor = pcursor
    max_pages = max(1, min(20, limit))
    for _ in range(max_pages):
        data = await _fetch_liked_page_via_api(page, current_cursor)
        page_videos = _extract_liked_videos_from_responses([data], limit=limit)
        for video in page_videos:
            photo_id = video.get("photo_id", "")
            if not photo_id or photo_id in seen:
                continue
            seen.add(photo_id)
            videos.append(video)
            if len(videos) >= limit:
                return videos
        next_cursor = data.get("pcursor", "")
        if not next_cursor or next_cursor == "no_more" or next_cursor == current_cursor:
            break
        current_cursor = next_cursor
        await page.wait(1.0)
    return videos


async def _fetch_liked_page_via_api(page: BrowserPage, pcursor: str) -> dict[str, Any]:
    result = await page.evaluate(f"""
    (async () => {{
      async function __douyinksKuaishouFetchLikedPage() {{
        const response = await fetch({LIKED_API_URL!r}, {{
          method: 'POST',
          credentials: 'include',
          referrer: location.href,
          headers: {{
            'Accept': 'application/json',
            'Content-Type': 'application/json',
          }},
          body: JSON.stringify({{'pcursor': {pcursor!r}, 'page': 'profile'}}),
        }});
        const text = await response.text();
        let data = null;
        try {{
          data = text ? JSON.parse(text) : null;
        }} catch (error) {{
          return {{ ok: false, status: response.status, error: `Invalid JSON: ${{text.slice(0, 200)}}` }};
        }}
        return {{ ok: response.ok, status: response.status, data }};
      }}
      return await __douyinksKuaishouFetchLikedPage();
    }})()
    """)
    if not isinstance(result, dict):
        raise KuaishouAPIError("Kuaishou liked API did not return an object.")
    data = result.get("data")
    if not result.get("ok"):
        raise KuaishouAPIError(f"Kuaishou liked API HTTP {result.get('status')}: {result.get('error') or data}")
    if not isinstance(data, dict):
        return {"pcursor": "", "feeds": []}
    code = data.get("result")
    if isinstance(code, int) and code != 1:
        raise KuaishouAPIError(f"Kuaishou API error {code}: {data.get('error_msg', 'unknown error')}")
    return data


async def _find_profile_url(page: BrowserPage) -> str:
    result = await page.evaluate("""
    (() => {
      const links = Array.from(document.querySelectorAll('a'))
        .map((a) => ({ href: a.href || '', text: (a.innerText || '').trim(), aria: a.getAttribute('aria-label') || '' }))
        .filter((item) => item.href.includes('/profile/'));
      const mine = links.find((item) => item.text.includes('我的') || item.aria.includes('我的'));
      return (mine || links[0] || {}).href || '';
    })()
    """)
    return result if isinstance(result, str) else ""


async def _install_liked_response_hook(page: BrowserPage) -> None:
    ok = await page.evaluate(LIKED_RESPONSE_HOOK)
    if not ok:
        raise KuaishouAPIError("无法安装快手 liked 响应监听器。")


async def _open_liked_tab(page: BrowserPage) -> None:
    result = await page.evaluate(OPEN_LIKED_TAB_SCRIPT)
    if result is True:
        await page.wait(2)
        return
    if isinstance(result, dict) and result.get("ok"):
        if result.get("alreadyActive"):
            await _click_tab_from_script(page, OPEN_WORKS_TAB_SCRIPT)
            await page.wait(1)
            result = await page.evaluate(OPEN_LIKED_TAB_SCRIPT)
        if isinstance(result, dict) and result.get("ok"):
            await _click_tab_from_result(page, result)
            await page.wait(2)
            return
    tabs = []
    if isinstance(result, dict):
        tabs = result.get("tabs") or []
    detail = f" 当前识别到的 tab: {tabs}" if tabs else ""
    raise KuaishouAPIError(f"无法打开快手点赞列表，请确认个人主页可访问。{detail}")


async def _click_tab_from_script(page: BrowserPage, script: str) -> None:
    result = await page.evaluate(script)
    if isinstance(result, dict) and result.get("ok"):
        await _click_tab_from_result(page, result)


async def _click_tab_from_result(page: BrowserPage, result: dict[str, Any]) -> None:
    x = result.get("x")
    y = result.get("y")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        await page.click(float(x), float(y))
        return


async def _collect_liked_videos(page: BrowserPage, *, limit: int) -> list[dict]:
    videos: list[dict] = []
    previous_count = -1
    stale_rounds = 0
    max_rounds = max(6, min(30, limit * 2))
    for _ in range(max_rounds):
        responses = await _read_liked_responses(page)
        videos = _extract_liked_videos_from_responses(responses, limit=limit)
        if len(videos) >= limit:
            break
        if len(videos) == previous_count:
            stale_rounds += 1
        else:
            stale_rounds = 0
        if stale_rounds >= 3:
            break
        previous_count = len(videos)
        await _scroll_liked_page(page)
        await page.wait(1.5)
    return videos[:limit]


async def _read_liked_responses(page: BrowserPage) -> list[dict[str, Any]]:
    value = await page.evaluate("""
    (() => {
      function __douyinksKuaishouReadLikedResponses() {
        return (window.__douyinksKuaishouLikedResponses || []).map((item) => item.data);
      }
      return __douyinksKuaishouReadLikedResponses();
    })()
    """)
    return value if isinstance(value, list) else []


async def _scroll_liked_page(page: BrowserPage) -> None:
    await page.evaluate("""
    (() => {
      function __douyinksKuaishouScrollLikedPage() {
        window.scrollTo(0, document.documentElement.scrollHeight || document.body.scrollHeight || 0);
        const nodes = Array.from(document.querySelectorAll('*'));
        for (const node of nodes) {
          if (node.scrollHeight > node.clientHeight + 120) {
            node.scrollTop = node.scrollHeight;
          }
        }
        return true;
      }
      return __douyinksKuaishouScrollLikedPage();
    })()
    """)


def _extract_liked_videos_from_responses(responses: list[dict[str, Any]], *, limit: int) -> list[dict]:
    videos: list[dict] = []
    seen: set[str] = set()
    for response in responses:
        if not isinstance(response, dict):
            continue
        feeds = response.get("feeds", [])
        if not isinstance(feeds, list):
            continue
        for item in feeds:
            if not isinstance(item, dict):
                continue
            video = _feed_to_video(item)
            photo_id = video.get("photo_id", "")
            if not photo_id or photo_id in seen:
                continue
            seen.add(photo_id)
            videos.append(video)
            if len(videos) >= limit:
                return videos
    return videos


def _feed_to_video(item: dict[str, Any]) -> dict[str, Any]:
    photo = item.get("photo", {})
    author = item.get("author", {})
    return {
        "photo_id": photo.get("id", ""),
        "caption": photo.get("caption", ""),
        "author_name": author.get("name", ""),
        "author_id": author.get("id", ""),
        "play_url": _pick_best_url(photo),
        "timestamp": photo.get("timestamp", 0),
    }


def _pick_best_url(photo: dict) -> str:
    manifest_h265 = photo.get("manifestH265", {})
    if isinstance(manifest_h265, dict):
        adaptation_sets = manifest_h265.get("adaptationSet", [])
        if adaptation_sets:
            representations = adaptation_sets[0].get("representation", [])
            if representations and representations[0].get("url"):
                return representations[0]["url"]
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
