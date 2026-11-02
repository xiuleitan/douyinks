import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from aiohttp.test_utils import TestServer
from click.testing import CliRunner

from douyinks.config import Settings
from douyinks.daemon import create_app
from douyinks.history import DownloadHistory
from douyinks.main import cli
from douyinks.sync_server import create_sync_app
from douyinks.sync_transfer import SyncTransferState


def existing_ledger(tmp_path):
    ledger = {"version": 1, "baseline_at": "2026-05-30T07:10:26.106191+00:00", "files": {
        "douyin:old": {"sync_status": "synced", "synced_at": "2026-06-01T00:00:00+00:00",
                       "synced_devices": ["original-phone"]},
    }}
    path = tmp_path / "sync_state.json"
    path.write_text(json.dumps(ledger, indent=4))
    return path, ledger


def record_download(tmp_path, platform, video_id):
    path = tmp_path / platform / "likes" / f"{video_id}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video-bytes")
    DownloadHistory(tmp_path / "download_history.json").record_success(platform, video_id, path, path.name)


@pytest.mark.asyncio
async def test_recovered_service_preserves_acks_and_serves_downloads_since_old_baseline(tmp_path, unused_tcp_port):
    path, original = existing_ledger(tmp_path)
    original_bytes = path.read_bytes()
    record_download(tmp_path, "douyin", "old")
    record_download(tmp_path, "kuaishou", "new")
    settings = Settings(str(tmp_path), sync_server_enabled=True, sync_server_port=unused_tcp_port,
                        sync_token="original-phone-token")
    base_url = f"http://127.0.0.1:{unused_tcp_port}"
    headers = {"Authorization": "Bearer original-phone-token"}

    async with TestServer(create_app(sync_settings=settings)) as bridge:
        async with httpx.AsyncClient(trust_env=False) as client:
            assert (await client.get(str(bridge.make_url("/ping")))).status_code == 200
            assert (await client.get(base_url + "/sync/health")).json()["version"] == 1
            assert (await client.get(base_url + "/sync/pending")).status_code == 401
            response = await client.get(base_url + "/sync/pending", headers=headers)
            files = response.json()["files"]
            assert [item["id"] for item in files] == ["kuaishou:new"]
            assert files[0]["download_url"] == "/sync/files/kuaishou%3Anew"
            assert path.read_bytes() == original_bytes

            download = await client.get(base_url + files[0]["download_url"], headers=headers)
            assert download.content == b"video-bytes"
            partial = await client.get(base_url + files[0]["download_url"],
                                       headers={**headers, "Range": "bytes=0-4"})
            assert partial.status_code == 206
            assert partial.content == b"video"
            response = await client.post(base_url + "/sync/ack", headers=headers,
                                         json={"device_id": "original-phone", "file_ids": ["kuaishou:new"]})
            assert response.json() == {"ok": True, "synced": 1}
            assert (await client.get(base_url + "/sync/pending", headers=headers)).json() == {"files": []}

    saved = json.loads(path.read_text())
    assert saved["baseline_at"] == original["baseline_at"]
    assert saved["files"]["douyin:old"] == original["files"]["douyin:old"]
    assert saved["files"]["kuaishou:new"]["synced_devices"] == ["original-phone"]
    async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
        with pytest.raises(httpx.ConnectError):
            await client.get(base_url + "/sync/health")


def test_stale_sync_readers_merge_parallel_acks_without_losing_old_records(tmp_path):
    path, original = existing_ledger(tmp_path)
    states = [SyncTransferState(path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(state.mark_synced, [f"kuaishou:{index}"], "phone")
                   for index, state in enumerate(states)]
        assert [future.result() for future in futures] == [1, 1, 1, 1]

    saved = json.loads(path.read_text())
    assert saved["baseline_at"] == original["baseline_at"]
    assert saved["files"]["douyin:old"] == original["files"]["douyin:old"]
    assert len(saved["files"]) == 5


def test_corrupt_ledger_is_preserved_instead_of_replaced(tmp_path):
    path = tmp_path / "sync_state.json"
    path.write_text("{broken original state")
    settings = Settings(str(tmp_path), sync_token="token")

    with pytest.raises(ValueError, match="保留"):
        create_sync_app(settings)

    assert path.read_text() == "{broken original state"


@pytest.mark.asyncio
async def test_original_phone_api_validates_auth_and_ack_bodies(tmp_path):
    settings = Settings(str(tmp_path), sync_token="token")
    async with TestServer(create_sync_app(settings)) as server, httpx.AsyncClient(trust_env=False) as client:
        for method, route in [("GET", "/sync/pending"), ("GET", "/sync/files/douyin:old"), ("POST", "/sync/ack")]:
            assert (await client.request(method, str(server.make_url(route)))).status_code == 401
        for payload in ([], {"file_ids": "not-a-list"}, {"file_ids": [1]}, {"file_ids": [], "device_id": 1}):
            response = await client.post(str(server.make_url("/sync/ack")), headers={"Authorization": "Bearer token"}, json=payload)
            assert response.status_code == 400


@pytest.mark.asyncio
async def test_sync_status_reports_existing_records_without_exposing_token(tmp_path, monkeypatch):
    path, _ = existing_ledger(tmp_path)
    settings = Settings(str(tmp_path), sync_token="private-token")
    async with TestServer(create_sync_app(settings)) as server:
        settings = Settings(str(tmp_path), sync_server_host="0.0.0.0", sync_server_port=server.port,
                            sync_token="private-token")
        monkeypatch.setattr(Settings, "load", classmethod(lambda cls: settings))
        monkeypatch.setattr("douyinks.network.get_lan_ips", lambda: ["192.168.1.23"])

        result = await asyncio.to_thread(CliRunner().invoke, cli, ["sync-status"])

        assert result.exit_code == 0, result.output
        assert f"http://192.168.1.23:{server.port}" in result.output
        assert "历史已同步记录: 1" in result.output
        assert "手机同步服务运行中" in result.output
        assert "private-token" not in result.output
