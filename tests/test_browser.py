import pytest

import douyinks.browser as browser_mod
from douyinks.browser import BrowserPage


@pytest.mark.asyncio
async def test_browser_page_click_sends_mouse_click_to_current_tab(monkeypatch):
    calls = []

    async def fake_send_command(action, **kwargs):
        calls.append((action, kwargs))
        return {"clicked": True}

    monkeypatch.setattr(browser_mod, "send_command", fake_send_command)
    page = BrowserPage(workspace="site:kuaishou", host="127.0.0.1", port=19826)
    page.tab_id = 123

    result = await page.click(10.5, 20.25)

    assert result == {"clicked": True}
    assert calls == [
        (
            "mouseClick",
            {
                "workspace": "site:kuaishou",
                "host": "127.0.0.1",
                "port": 19826,
                "tabId": 123,
                "x": 10.5,
                "y": 20.25,
            },
        )
    ]


@pytest.mark.asyncio
async def test_browser_page_can_control_kuaishou_liked_capture(monkeypatch):
    calls = []

    async def fake_send_command(action, **kwargs):
        calls.append((action, kwargs))
        return {"ok": True}

    monkeypatch.setattr(browser_mod, "send_command", fake_send_command)
    page = BrowserPage(workspace="site:kuaishou", host="127.0.0.1", port=19826)

    await page.start_kuaishou_liked_capture()
    await page.read_kuaishou_liked_capture()
    await page.clear_kuaishou_liked_capture()

    assert calls == [
        (
            "kuaishouLikedCapture",
            {
                "workspace": "site:kuaishou",
                "host": "127.0.0.1",
                "port": 19826,
                "op": "start",
            },
        ),
        (
            "kuaishouLikedCapture",
            {
                "workspace": "site:kuaishou",
                "host": "127.0.0.1",
                "port": 19826,
                "op": "read",
            },
        ),
        (
            "kuaishouLikedCapture",
            {
                "workspace": "site:kuaishou",
                "host": "127.0.0.1",
                "port": 19826,
                "op": "clear",
            },
        ),
    ]
