import pytest

from douyinks.platforms.douyin import detail as detail_mod


class FakePage:
    def __init__(self, dom_media=None):
        self.dom_media = dom_media or {"video_urls": [], "image_urls": []}
        self.gotourls = []

    async def goto(self, url):
        self.gotourls.append(url)

    async def wait(self, _seconds):
        return None

    async def evaluate(self, _js):
        return self.dom_media


@pytest.mark.asyncio
async def test_douyin_detail_extracts_image_urls(monkeypatch):
    async def fake_fetch(_page, _method, _url, headers):
        return {
            "aweme_detail": {
                "aweme_id": "1234567890123",
                "desc": "图文",
                "author": {"nickname": "Alice", "unique_id": "alice"},
                "create_time": 111,
                "images": [
                    {"url_list": ["https://example.test/1.jpg"]},
                    {"url_list": ["https://example.test/2.webp"]},
                ],
            }
        }

    monkeypatch.setattr(detail_mod, "browser_fetch", fake_fetch)

    result = await detail_mod.run(FakePage(), "1234567890123")

    assert result == [{
        "aweme_id": "1234567890123",
        "desc": "图文",
        "author": "Alice",
        "author_douyin_id": "alice",
        "create_time": 111,
        "media_type": "image",
        "play_url": "",
        "image_urls": ["https://example.test/1.jpg", "https://example.test/2.webp"],
        "video_urls": [],
    }]


@pytest.mark.asyncio
async def test_douyin_detail_extracts_child_video_urls_from_api(monkeypatch):
    async def fake_fetch(_page, _method, _url, headers):
        return {
            "aweme_detail": {
                "aweme_id": "1234567890123",
                "desc": "子视频",
                "author": {"nickname": "Alice", "unique_id": "alice"},
                "create_time": 111,
                "images": [
                    {"video": {"play_addr": {"url_list": ["https://example.test/1.mp4"]}}},
                    {"video_info": {"play_addr": {"url_list": ["https://example.test/2.mp4"]}}},
                ],
            }
        }

    monkeypatch.setattr(detail_mod, "browser_fetch", fake_fetch)

    result = await detail_mod.run(FakePage(), "1234567890123")

    assert result[0]["media_type"] == "mixed"
    assert result[0]["video_urls"] == ["https://example.test/1.mp4", "https://example.test/2.mp4"]


@pytest.mark.asyncio
async def test_douyin_detail_uses_one_url_per_child_video(monkeypatch):
    async def fake_fetch(_page, _method, _url, headers):
        return {
            "aweme_detail": {
                "aweme_id": "1234567890123",
                "desc": "子视频多 CDN",
                "author": {"nickname": "Alice", "unique_id": "alice"},
                "create_time": 111,
                "aweme_type": 68,
                "images": [
                    {
                        "video": {
                            "play_addr": {
                                "url_list": [
                                    "https://cdn-a.example.test/child-1.mp4",
                                    "https://cdn-b.example.test/child-1.mp4",
                                    "https://www.douyin.com/aweme/v1/play/?video_id=child-1",
                                ],
                            },
                        },
                    },
                    {
                        "video": {
                            "play_addr": {
                                "url_list": [
                                    "https://cdn-a.example.test/child-2.mp4",
                                    "https://cdn-b.example.test/child-2.mp4",
                                    "https://www.douyin.com/aweme/v1/play/?video_id=child-2",
                                ],
                            },
                        },
                    },
                ],
            }
        }

    monkeypatch.setattr(detail_mod, "browser_fetch", fake_fetch)

    result = await detail_mod.run(FakePage(), "1234567890123")

    assert result[0]["video_urls"] == [
        "https://cdn-a.example.test/child-1.mp4",
        "https://cdn-a.example.test/child-2.mp4",
    ]


@pytest.mark.asyncio
async def test_douyin_detail_extracts_note_images_and_child_videos(monkeypatch):
    async def fake_fetch(_page, _method, _url, headers):
        return {
            "aweme_detail": {
                "aweme_id": "1234567890123",
                "desc": "note 子视频",
                "author": {"nickname": "Alice", "unique_id": "alice"},
                "create_time": 111,
                "aweme_type": 68,
                "video": {
                    "play_addr": {
                        "url_list": ["https://example.test/top-level-preview.mp4"],
                    },
                },
                "images": [
                    {
                        "url_list": ["https://example.test/cover-1.webp"],
                        "video": {"play_addr": {"url_list": ["https://example.test/child-1.mp4"]}},
                    },
                    {
                        "url_list": ["https://example.test/cover-2.webp"],
                        "video": {"play_addr": {"url_list": ["https://example.test/child-2.mp4"]}},
                    },
                ],
            }
        }

    monkeypatch.setattr(detail_mod, "browser_fetch", fake_fetch)

    result = await detail_mod.run(FakePage(), "1234567890123")

    assert result[0]["media_type"] == "mixed"
    assert result[0]["play_url"] == ""
    assert result[0]["image_urls"] == ["https://example.test/cover-1.webp", "https://example.test/cover-2.webp"]
    assert result[0]["video_urls"] == ["https://example.test/child-1.mp4", "https://example.test/child-2.mp4"]


@pytest.mark.asyncio
async def test_douyin_detail_extracts_mixed_note_image_and_video_children(monkeypatch):
    async def fake_fetch(_page, _method, _url, headers):
        return {
            "aweme_detail": {
                "aweme_id": "1234567890123",
                "desc": "note 图文和视频",
                "author": {"nickname": "Alice", "unique_id": "alice"},
                "create_time": 111,
                "aweme_type": 68,
                "video": {"play_addr": {"url_list": ["https://example.test/top-level-preview.mp4"]}},
                "images": [
                    {"url_list": ["https://example.test/still.webp"]},
                    {
                        "url_list": ["https://example.test/video-cover.webp"],
                        "video": {"play_addr": {"url_list": ["https://example.test/child.mp4"]}},
                    },
                ],
            }
        }

    monkeypatch.setattr(detail_mod, "browser_fetch", fake_fetch)

    result = await detail_mod.run(FakePage(), "1234567890123")

    assert result[0]["media_type"] == "mixed"
    assert result[0]["play_url"] == ""
    assert result[0]["image_urls"] == ["https://example.test/still.webp", "https://example.test/video-cover.webp"]
    assert result[0]["video_urls"] == ["https://example.test/child.mp4"]


@pytest.mark.asyncio
async def test_douyin_detail_falls_back_to_note_dom_media(monkeypatch):
    async def fake_fetch(_page, _method, _url, headers):
        return {
            "aweme_detail": {
                "aweme_id": "1234567890123",
                "desc": "DOM 子视频",
                "author": {"nickname": "Alice", "unique_id": "alice"},
                "create_time": 111,
            }
        }

    page = FakePage(dom_media={"video_urls": ["https://example.test/dom.mp4"], "image_urls": []})
    monkeypatch.setattr(detail_mod, "browser_fetch", fake_fetch)

    result = await detail_mod.run(page, "1234567890123")

    assert page.gotourls == ["https://www.douyin.com/note/1234567890123"]
    assert result[0]["media_type"] == "mixed"
    assert result[0]["video_urls"] == ["https://example.test/dom.mp4"]
