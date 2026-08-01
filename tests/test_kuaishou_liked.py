import pytest

from douyinks.platforms.kuaishou import liked


class FakePage:
    def __init__(self, *, liked_already_active=False):
        self.gotos = []
        self.waits = []
        self.evaluations = []
        self.clicks = []
        self.response_reads = 0
        self.liked_already_active = liked_already_active
        self.captured_payload = {
            "responses": [
                {
                    "data": {
                        "pcursor": "no_more",
                        "feeds": [
                            {
                                "photo": {
                                    "id": "captured-1",
                                    "caption": "captured",
                                    "timestamp": 333,
                                    "photoUrls": [{"url": "https://example.test/captured.mp4"}],
                                },
                                "author": {"id": "a3", "name": "carol"},
                            }
                        ],
                    }
                }
            ],
            "errors": [],
        }

    async def goto(self, url):
        self.gotos.append(url)
        return {"url": url}

    async def wait(self, seconds):
        self.waits.append(seconds)

    async def evaluate(self, js):
        self.evaluations.append(js)
        if "querySelectorAll('a')" in js:
            return "https://www.kuaishou.com/profile/3xprofile?source=NewReco"
        if "__douyinksKuaishouLikedHookInstalled" in js:
            return True
        if "__douyinksKuaishouFetchLikedPage" in js:
            return self._api_page(js)
        if "__douyinksKuaishouOpenWorksTab" in js:
            return {"ok": True, "clickedText": "作品", "x": 42.0, "y": 365.0}
        if "__douyinksKuaishouOpenLikedTab" in js:
            if self.liked_already_active:
                self.liked_already_active = False
                return {"ok": True, "alreadyActive": True}
            return {"ok": True, "clickedText": "点赞", "x": 144.0, "y": 365.0}
        if "__douyinksKuaishouScrollLikedPage" in js:
            return True
        if "__douyinksKuaishouReadLikedResponses" in js:
            self.response_reads += 1
            if self.response_reads == 1:
                return [
                    {
                        "pcursor": "cursor-2",
                        "feeds": [
                            {
                                "photo": {
                                    "id": "p1",
                                    "caption": "first",
                                    "timestamp": 111,
                                    "photoUrls": [{"url": "https://example.test/1.mp4"}],
                                },
                                "author": {"id": "a1", "name": "alice"},
                            }
                        ],
                    }
                ]
            return [
                {
                    "pcursor": "no_more",
                    "feeds": [
                        {
                            "photo": {
                                "id": "p1",
                                "caption": "duplicate",
                                "timestamp": 111,
                                "photoUrls": [{"url": "https://example.test/1.mp4"}],
                            },
                            "author": {"id": "a1", "name": "alice"},
                        },
                        {
                            "photo": {
                                "id": "p2",
                                "caption": "second",
                                "timestamp": 222,
                                "photoUrls": [{"url": "https://example.test/2.mp4"}],
                            },
                            "author": {"id": "a2", "name": "bob"},
                        },
                    ],
                }
            ]
        return None

    def _api_page(self, js):
        if "cursor-2" in js:
            return {
                "ok": True,
                "data": {
                    "pcursor": "no_more",
                    "feeds": [
                        {
                            "photo": {
                                "id": "p2",
                                "caption": "second",
                                "timestamp": 222,
                                "photoUrls": [{"url": "https://example.test/2.mp4"}],
                            },
                            "author": {"id": "a2", "name": "bob"},
                        }
                    ],
                },
            }
        return {
            "ok": True,
            "data": {
                "pcursor": "cursor-2",
                "feeds": [
                    {
                        "photo": {
                            "id": "p1",
                            "caption": "first",
                            "timestamp": 111,
                            "photoUrls": [{"url": "https://example.test/1.mp4"}],
                        },
                        "author": {"id": "a1", "name": "alice"},
                    }
                ],
            },
        }

    async def click(self, x, y):
        self.clicks.append((x, y))
        return {"clicked": True}

    async def read_kuaishou_liked_capture(self):
        return self.captured_payload


@pytest.mark.asyncio
async def test_kuaishou_liked_run_collects_signed_web_responses_by_scrolling():
    page = FakePage()

    videos = await liked.run(page, limit=2)

    assert page.gotos == [
        "https://www.kuaishou.com",
        "https://www.kuaishou.com/profile/3xprofile?source=NewReco",
    ]
    assert [video["photo_id"] for video in videos] == ["p1", "p2"]
    assert page.clicks == []
    assert videos[0]["play_url"] == "https://example.test/1.mp4"
    assert any("__douyinksKuaishouFetchLikedPage" in js for js in page.evaluations)


@pytest.mark.asyncio
async def test_kuaishou_liked_reopens_liked_tab_when_it_is_already_active():
    page = FakePage(liked_already_active=True)

    videos = await liked.run(page, limit=2)

    assert [video["photo_id"] for video in videos] == ["p1", "p2"]
    assert page.clicks == []
    assert not any("__douyinksKuaishouOpenWorksTab" in js for js in page.evaluations)


def test_extract_liked_videos_from_signed_web_responses_deduplicates():
    videos = liked._extract_liked_videos_from_responses(
        [
            {
                "feeds": [
                    {
                        "photo": {"id": "p1", "timestamp": 111, "photoUrls": [{"url": "https://example.test/1.mp4"}]},
                        "author": {"id": "a1"},
                    }
                ]
            },
            {
                "feeds": [
                    {
                        "photo": {"id": "p1", "timestamp": 111, "photoUrls": [{"url": "https://example.test/1.mp4"}]},
                        "author": {"id": "a1"},
                    },
                    {
                        "photo": {"id": "p2", "timestamp": 222, "photoUrls": [{"url": "https://example.test/2.mp4"}]},
                        "author": {"id": "a2"},
                    },
                ]
            },
        ],
        limit=10,
    )

    assert [video["photo_id"] for video in videos] == ["p1", "p2"]


@pytest.mark.asyncio
async def test_read_captured_liked_videos_uses_extension_responses():
    videos = await liked.read_captured(FakePage(), limit=5)

    assert [video["photo_id"] for video in videos] == ["captured-1"]


@pytest.mark.asyncio
async def test_read_captured_liked_videos_waits_for_pending_extension_response():
    class PendingCapturePage(FakePage):
        async def wait(self, seconds):
            await super().wait(seconds)
            self.captured_payload["pending"] = 0

    page = PendingCapturePage()
    page.captured_payload["pending"] = 1

    videos = await liked.read_captured(page, limit=5)

    assert [video["photo_id"] for video in videos] == ["captured-1"]
    assert page.waits == [liked.CAPTURE_SETTLE_POLL_SECONDS]


@pytest.mark.asyncio
async def test_read_captured_liked_videos_refuses_partial_capture_after_response_error():
    page = FakePage()
    page.captured_payload["failed"] = 1

    with pytest.raises(liked.KuaishouAPIError, match="为避免漏下载"):
        await liked.read_captured(page, limit=5)


@pytest.mark.asyncio
async def test_captured_summary_counts_unique_videos_from_extension_responses():
    page = FakePage()
    page.captured_payload = {
        "responses": [
            {
                "data": {
                    "feeds": [
                        {
                            "photo": {"id": "p1", "timestamp": 111, "photoUrls": [{"url": "https://example.test/1.mp4"}]},
                            "author": {"id": "a1"},
                        },
                        {
                            "photo": {"id": "p1", "timestamp": 111, "photoUrls": [{"url": "https://example.test/1.mp4"}]},
                            "author": {"id": "a1"},
                        },
                    ]
                }
            },
            {
                "data": {
                    "feeds": [
                        {
                            "photo": {"id": "p2", "timestamp": 222, "photoUrls": [{"url": "https://example.test/2.mp4"}]},
                            "author": {"id": "a2"},
                        }
                    ]
                }
            },
        ],
        "errors": [{"error": "late body"}],
        "matched": 3,
        "completed": 2,
        "failed": 1,
        "pending": 0,
        "dropped": 0,
    }

    summary = await liked.captured_summary(page)

    assert summary["video_count"] == 2
    assert summary["response_count"] == 2
    assert summary["matched_response_count"] == 3
    assert summary["completed_response_count"] == 2
    assert summary["error_count"] == 1
    assert summary["pending_response_count"] == 0
    assert summary["dropped_response_count"] == 0
    assert [video["photo_id"] for video in summary["videos"]] == ["p1", "p2"]


def test_pick_best_url_prefers_manifest_h265_representation():
    assert liked._pick_best_url(
        {
            "manifestH265": {
                "adaptationSet": [
                    {
                        "representation": [
                            {"url": "https://example.test/h265.mp4"},
                        ]
                    }
                ]
            },
            "photoUrls": [{"url": "https://example.test/basic.mp4"}],
        }
    ) == "https://example.test/h265.mp4"


def test_open_liked_tab_script_targets_tab_items_not_profile_stats():
    assert ".tab-nav [role=\"button\"]" in liked.OPEN_LIKED_TAB_SCRIPT
    assert "const selectors = [" in liked.OPEN_LIKED_TAB_SCRIPT
    assert "const seen = new Set();" in liked.OPEN_LIKED_TAB_SCRIPT
    assert "textContent" in liked.OPEN_LIKED_TAB_SCRIPT
    assert "item.text.includes('获赞')" in liked.OPEN_LIKED_TAB_SCRIPT
    assert "alreadyActive" in liked.OPEN_LIKED_TAB_SCRIPT
    assert "x: rect.left + rect.width / 2" in liked.OPEN_LIKED_TAB_SCRIPT
    assert "item.text.length > 20" in liked.OPEN_LIKED_TAB_SCRIPT
    assert "text.length <= 20" in liked.OPEN_LIKED_TAB_SCRIPT
    assert "__douyinksKuaishouOpenWorksTab" in liked.OPEN_WORKS_TAB_SCRIPT
