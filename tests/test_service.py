import os
import time
from pathlib import Path

from service import AppDB, CredentialStore, Scheduler, SyncResult, SyncService
from wechat_mp_fetcher import Article, save_article


def test_source_crud_and_feed(tmp_path: Path):
    db = AppDB(tmp_path / "db.sqlite")
    source = db.add_source(source_value="MP_WXS_123", name="测试号", interval_minutes=10)
    # Web 管理端强制最低 30 分钟。
    assert source.sync_interval_minutes == 30
    with db.connect() as conn:
        save_article(conn, Article("r1", source.book_id, "文章1", url="https://example.com", publish_at=1700000000))
        conn.commit()
    creds = CredentialStore(tmp_path / "credentials.json")
    service = SyncService(db, creds)
    xml = service.feed_bytes(source.id, "http://localhost:8080").decode("utf-8")
    assert "测试号" in xml
    assert "文章1" in xml
    assert db.get_source(source.id).article_count == 1


def test_credentials_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("WEREAD_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WEREAD_VID", raising=False)
    store = CredentialStore(tmp_path / "credentials.json")
    store.save("abcdefghijk", "123456")
    assert store.get() == ("abcdefghijk", "123456")
    assert store.status()["token_hint"] == "abcd…hijk"
    if os.name != "nt":
        assert (store.path.stat().st_mode & 0o777) == 0o600


def test_scheduler_setting_persists(tmp_path: Path):
    db = AppDB(tmp_path / "db.sqlite")
    creds = CredentialStore(tmp_path / "credentials.json")
    service = SyncService(db, creds)
    db.set_setting("scheduler_enabled", "0")
    scheduler = Scheduler(db, service)
    assert scheduler.enabled is False


def test_content_fetch_is_disabled_for_new_and_existing_sources(tmp_path: Path):
    path = tmp_path / "db.sqlite"
    db = AppDB(path)
    source = db.add_source(source_value="MP_WXS_999", name="正文开关", fetch_content=True)
    assert db.get_source(source.id).fetch_content is False

    with db.connect() as conn:
        conn.execute("UPDATE sources SET fetch_content=1 WHERE id=?", (source.id,))
        conn.commit()
    assert db.get_source(source.id).fetch_content is True

    reopened = AppDB(path)
    assert reopened.get_source(source.id).fetch_content is False


def test_sync_auto_refreshes_once_on_auth_expired(tmp_path: Path, monkeypatch):
    import service as service_module
    from wechat_mp_fetcher import AuthExpiredError
    from weread_auth import WeReadCredentials

    db = AppDB(tmp_path / "db.sqlite")
    source = db.add_source(source_value="MP_WXS_123", name="测试号", fetch_content=False)
    creds = CredentialStore(tmp_path / "credentials.json")
    creds.save_record(WeReadCredentials(
        vid="123", accessToken="old-token", refreshToken="refresh", deviceId="device-1"
    ))

    calls = {"clients": 0, "refresh": 0}

    class FakeMobileClient:
        def __init__(self, token, vid, **kwargs):
            self.token = token
            calls["clients"] += 1

        def get_articles(self, book_id, **kwargs):
            if self.token == "old-token":
                raise AuthExpiredError("expired")
            return [Article("r-auto", book_id, "自动续期文章", publish_at=1700000010)]

    class FakeAuth:
        def version_headers(self):
            return {}

        def refresh(self, record):
            calls["refresh"] += 1
            record.accessToken = "new-token"
            record.refreshToken = "refresh-rotated"
            return record

    monkeypatch.setattr(service_module, "WeReadMobileClient", FakeMobileClient)
    sync = SyncService(db, creds, auth_client=FakeAuth())
    result = sync.sync_source(source.id)
    assert result.status == "ok"
    assert result.new_count == 1
    assert calls["refresh"] == 1
    assert creds.get_record().accessToken == "new-token"
    assert creds.get_record().refreshToken == "refresh-rotated"


def test_risk_control_does_not_refresh(tmp_path: Path, monkeypatch):
    import service as service_module
    from wechat_mp_fetcher import RiskControlError
    from weread_auth import WeReadCredentials

    db = AppDB(tmp_path / "db.sqlite")
    source = db.add_source(source_value="MP_WXS_456", name="风控测试", fetch_content=False)
    creds = CredentialStore(tmp_path / "credentials.json")
    creds.save_record(WeReadCredentials(
        vid="456", accessToken="token", refreshToken="refresh", deviceId="device-2"
    ))
    calls = {"refresh": 0}

    class FakeMobileClient:
        def __init__(self, *args, **kwargs):
            pass
        def get_articles(self, *args, **kwargs):
            raise RiskControlError("-2041")

    class FakeAuth:
        def version_headers(self):
            return {}
        def refresh(self, record):
            calls["refresh"] += 1
            return record

    monkeypatch.setattr(service_module, "WeReadMobileClient", FakeMobileClient)
    sync = SyncService(db, creds, auth_client=FakeAuth())
    result = sync.sync_source(source.id)
    assert result.status == "risk_control"
    assert calls["refresh"] == 0


def test_backfill_missing_article_url(tmp_path: Path, monkeypatch):
    import service as service_module
    from weread_auth import WeReadCredentials

    db = AppDB(tmp_path / "db.sqlite")
    source = db.add_source(source_value="MP_WXS_789", name="链接测试", fetch_content=False)
    with db.connect() as conn:
        save_article(conn, Article("r-missing", source.book_id, "缺链接文章", publish_at=1700000000))
        conn.commit()
    creds = CredentialStore(tmp_path / "credentials.json")
    creds.save_record(WeReadCredentials(vid="789", accessToken="token", refreshToken="refresh", deviceId="dev"))

    class FakeMobileClient:
        def __init__(self, *args, **kwargs):
            pass
        def resolve_article_url(self, review_id):
            assert review_id == "r-missing"
            return "https://mp.weixin.qq.com/s/backfilled-token"

    class FakeAuth:
        def version_headers(self):
            return {}

    monkeypatch.setattr(service_module, "WeReadMobileClient", FakeMobileClient)
    sync = SyncService(db, creds, auth_client=FakeAuth())
    resolved, failed = sync.backfill_source_urls(source.id, limit=5)
    assert (resolved, failed) == (1, 0)
    assert db.article_by_review("r-missing").url == "https://mp.weixin.qq.com/s/backfilled-token"


def test_sync_jitter_widens_next_sync_window(tmp_path: Path):
    db = AppDB(tmp_path / "db.sqlite")
    source = db.add_source(source_value="MP_WXS_222", name="抖动测试", interval_minutes=60, jitter_minutes=30)
    assert source.sync_jitter_minutes == 30
    run_id = db.mark_sync_start(source.id)
    before = int(time.time())
    db.mark_sync_finish(source, run_id, SyncResult(source.id, 0, 0, 0, "ok", ""))
    after = int(time.time())
    updated = db.get_source(source.id)
    assert before + 60 * 60 <= updated.next_sync_at <= after + 90 * 60


def test_risk_control_pauses_auto_sync_until_manual_success(tmp_path: Path):
    db = AppDB(tmp_path / "db.sqlite")
    source = db.add_source(source_value="MP_WXS_333", name="风控暂停测试", interval_minutes=60)

    run_id = db.mark_sync_start(source.id)
    db.mark_sync_finish(source, run_id, SyncResult(source.id, 0, 0, 0, "risk_control", "微信读书返回风控/限频错误 -2041: -2041"))
    paused = db.get_source(source.id)
    assert paused.enabled is False
    assert paused.next_sync_at == 0
    # 暂停之后不应该再出现在调度器的待同步列表里。
    assert paused.id not in {s.id for s in db.due_sources()}

    # 用户手动同步成功，视为确认账号已经恢复，自动同步重新打开。
    source = db.get_source(source.id)
    run_id = db.mark_sync_start(source.id)
    db.mark_sync_finish(source, run_id, SyncResult(source.id, 5, 5, 0, "ok", ""))
    recovered = db.get_source(source.id)
    assert recovered.enabled is True
    assert recovered.next_sync_at > int(time.time())


def test_client_for_shares_one_rate_limiter(tmp_path: Path):
    from weread_auth import WeReadCredentials

    db = AppDB(tmp_path / "db.sqlite")
    creds = CredentialStore(tmp_path / "credentials.json")
    creds.save_record(WeReadCredentials(vid="1", accessToken="token", refreshToken="r", deviceId="d"))
    sync = SyncService(db, creds)
    record = creds.get_record()
    client_a = sync._client_for(record)
    client_b = sync._client_for(record)
    # 不同 client 实例必须共用同一个 limiter，跨请求的最小间隔才是真的全局生效。
    assert client_a.limiter is client_b.limiter is sync._limiter


def test_refresh_skips_redundant_call_when_already_refreshed(tmp_path: Path):
    from weread_auth import WeReadCredentials

    db = AppDB(tmp_path / "db.sqlite")
    creds = CredentialStore(tmp_path / "credentials.json")
    creds.save_record(WeReadCredentials(vid="1", accessToken="old", refreshToken="r", deviceId="d"))

    class FakeAuth:
        def refresh(self, record):
            raise AssertionError("不应该真的发起续期请求")

    sync = SyncService(db, creds, auth_client=FakeAuth())

    # 模拟并发：本线程判断需要刷新时读到的是旧 token，但真正进锁后
    # 发现已经被“另一个线程”刷新成了新 token。
    calls = {"n": 0}
    real_get_record = creds.get_record

    def fake_get_record():
        calls["n"] += 1
        record = real_get_record()
        record.accessToken = "old" if calls["n"] == 1 else "new-from-another-thread"
        return record

    sync.credentials.get_record = fake_get_record
    result = sync.refresh_credentials()
    assert result.accessToken == "new-from-another-thread"
