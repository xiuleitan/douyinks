from douyinks.platforms.douyin import scrape_ids


def test_douyin_scroll_script_scrolls_nested_scroll_containers():
    assert "document.querySelectorAll('*')" in scrape_ids.SCROLL_JS
    assert "node.scrollTop = node.scrollHeight" in scrape_ids.SCROLL_JS
    assert "scrollableCount" in scrape_ids.SCROLL_JS


def test_douyin_stagnant_limit_grows_for_large_downloads():
    assert scrape_ids._stagnant_limit(20) == 3
    assert scrape_ids._stagnant_limit(400) > 3
