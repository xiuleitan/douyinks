import json

import pytest

from douyinks.config import Settings
from douyinks.reports import load_summary, save_summary


def test_saved_result_keeps_counts_without_temporary_media_urls(tmp_path):
    settings = Settings(str(tmp_path))
    result = {"requested": 3, "available": 3, "success": 1, "failed": 1, "skipped": 1,
              "output_dir": str(tmp_path / "videos"), "source": "captured",
              "items": [{"play_url": "https://example.test/private?token=secret"}]}

    summary = save_summary(settings, "kuaishou", result, 12.345)

    assert load_summary(settings, "kuaishou") == summary
    assert summary["elapsed_seconds"] == 12.3
    assert summary["completed_at"]
    contents = (tmp_path / "kuaishou_last_download.json").read_text()
    assert "token" not in contents
    assert not (tmp_path / "kuaishou_last_download.json.tmp").exists()


@pytest.mark.parametrize("data", [[], {"platform": "douyin"}, {"platform": "kuaishou", "failed": -1}])
def test_invalid_saved_results_do_not_return_fake_counts(tmp_path, data):
    (tmp_path / "kuaishou_last_download.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_summary(Settings(str(tmp_path)), "kuaishou")
