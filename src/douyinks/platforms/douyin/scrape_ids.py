from ...browser import BrowserPage


EXTRACT_IDS_JS = """
(() => {
  const ids = new Set();
  const ordered = [];
  document.querySelectorAll('a[href*="/video/"], a[href*="/note/"]').forEach(a => {
    const match = a.href.match(/\\/(video|note)\\/(\\d+)/);
    if (match && !ids.has(match[2])) {
      ids.add(match[2]);
      ordered.push(match[2]);
    }
  });
  return ordered;
})()
"""

SCROLL_JS = """
(() => {
  const root = document.scrollingElement || document.documentElement || document.body;
  const before = root.scrollTop;
  window.scrollTo(0, Math.max(document.body.scrollHeight, document.documentElement.scrollHeight));
  root.scrollTop = root.scrollHeight;

  let scrollableCount = 0;
  document.querySelectorAll('*').forEach((node) => {
    if (node.scrollHeight > node.clientHeight + 120) {
      node.scrollTop = node.scrollHeight;
      scrollableCount += 1;
    }
  });

  return {
    height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
    scrollTop: root.scrollTop,
    moved: root.scrollTop !== before,
    scrollableCount,
  };
})()
"""


def _stagnant_limit(limit: int) -> int:
    return max(3, min(12, limit // 50 + 3))


async def run(page: BrowserPage, limit: int, scroll_delay: float = 2.0) -> list[str]:
    await page.goto("https://www.douyin.com/user/self?from_tab_name=main&showTab=like")
    await page.wait(3)

    all_ids: list[str] = []
    seen: set[str] = set()
    stagnant_rounds = 0
    previous_count = 0

    max_stagnant_rounds = _stagnant_limit(limit)

    while len(all_ids) < limit and stagnant_rounds < max_stagnant_rounds:
        ids = await page.evaluate(EXTRACT_IDS_JS)
        if isinstance(ids, list):
            for video_id in ids:
                if video_id not in seen:
                    seen.add(video_id)
                    all_ids.append(video_id)
                    if len(all_ids) >= limit:
                        break

        if len(all_ids) == previous_count:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
            previous_count = len(all_ids)

        if len(all_ids) < limit:
            await page.evaluate(SCROLL_JS)
            await page.wait(scroll_delay)

    return all_ids[:limit]
