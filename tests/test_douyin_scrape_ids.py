import pytest

from douyinks.platforms.douyin import scrape_ids


def test_douyin_scroll_script_scrolls_nested_scroll_containers():
    assert "document.querySelectorAll('*')" in scrape_ids.SCROLL_JS
    assert "node.scrollTop = node.scrollHeight" in scrape_ids.SCROLL_JS
    assert "scrollableCount" in scrape_ids.SCROLL_JS


def test_douyin_stagnant_limit_grows_for_large_downloads():
    assert scrape_ids._stagnant_limit(20) == 3
    assert scrape_ids._stagnant_limit(400) > 3


@pytest.mark.asyncio
@pytest.mark.parametrize("batches,limit,expected_ids,expected_counts", [
    ([["a", "b", "a"], ["b", "c", "d"]], 3, ["a", "b", "c"], [0, 2, 3]),
    ([["a", "b"]] * 4, 5, ["a", "b"], [0, 2]),
    ([[]] * 3, 5, [], [0]),
])
async def test_list_progress_counts_unique_entries_during_scrolling(batches, limit, expected_ids, expected_counts):
    snapshots = []
    responses = iter(batches)

    class Page:
        async def goto(self, url):
            # Report zero before navigation or page loading can block.
            assert snapshots == [(0, limit)]

        async def wait(self, seconds):
            pass

        async def evaluate(self, js):
            if js == scrape_ids.EXTRACT_IDS_JS:
                return next(responses)
            return {}

    result = await scrape_ids.run(Page(), limit, progress=lambda count, total: snapshots.append((count, total)))

    assert result == expected_ids
    assert snapshots == [(count, limit) for count in expected_counts]
