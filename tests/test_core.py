from wechat_mp_fetcher import (
    Article,
    book_id_from_article_url,
    decode_biz,
    open_db,
    parse_articles_payload,
    render_rss,
    save_article,
)


def test_decode_biz_and_bookid():
    assert decode_biz("MzI0Mzk0ODI5OQ==") == "3243948299"
    assert book_id_from_article_url("https://mp.weixin.qq.com/s?__biz=MzI0Mzk0ODI5OQ==&mid=1") == "MP_WXS_3243948299"


def test_parse_articles_payload():
    payload = {
        "reviews": [
            {
                "createTime": 1700000000,
                "subReviews": [
                    {
                        "review": {
                            "reviewId": "r1",
                            "mpInfo": {
                                "title": "测试文章",
                                "content": "摘要",
                                "time": 1700000001,
                                "originalId": "https://mp.weixin.qq.com/s/abc",
                                "readNum": 10,
                                "likeNum": 2,
                            },
                        }
                    }
                ],
            }
        ]
    }
    articles = parse_articles_payload(payload, "MP_WXS_1")
    assert len(articles) == 1
    assert articles[0].review_id == "r1"
    assert articles[0].title == "测试文章"
    assert articles[0].url == "https://mp.weixin.qq.com/s/abc"


def test_render_rss():
    data = render_rss([Article("r1", "MP_WXS_1", "Hello", url="https://example.com", publish_at=1700000000)], feed_title="Feed")
    text = data.decode("utf-8")
    assert "<title>Feed</title>" in text
    assert "<guid isPermaLink=\"false\">r1</guid>" in text


def test_new_style_short_url_html_window_biz():
    from article_identity import extract_identity_from_html
    url = "https://mp.weixin.qq.com/s/LQ16ZvHq4sc0-oplZUpFog"
    html = '''
    <html><head>
      <meta property="og:title" content="新式短链接文章">
      <meta property="og:article:author" content="测试公众号">
    </head><body>
    <script>window.biz = "MzI0Mzk0ODI5OQ==";</script>
    </body></html>
    '''
    item = extract_identity_from_html(html, url)
    assert item is not None
    assert item.biz == "MzI0Mzk0ODI5OQ=="
    assert item.bid == "3243948299"
    assert item.book_id == "MP_WXS_3243948299"
    assert item.account_name == "测试公众号"


def test_new_style_short_url_html_msg_link():
    from article_identity import extract_identity_from_html
    url = "https://mp.weixin.qq.com/s/short-token"
    html = '''<html><script>
      var msg_link = "https://mp.weixin.qq.com/s?__biz=MzI0Mzk0ODI5OQ==&amp;mid=1&amp;idx=1";
    </script></html>'''
    item = extract_identity_from_html(html, url)
    assert item is not None
    assert item.bid == "3243948299"
    assert item.method == "html-msg-link"


def test_resolve_short_url_with_static_html(monkeypatch):
    from article_identity import resolve_article_identity

    class FakeResponse:
        status_code = 200
        url = "https://mp.weixin.qq.com/s/LQ16ZvHq4sc0-oplZUpFog"
        text = '<html><script>var biz="MzI0Mzk0ODI5OQ==";</script></html>'
        def raise_for_status(self):
            return None

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse()

    item = resolve_article_identity(
        "https://mp.weixin.qq.com/s/LQ16ZvHq4sc0-oplZUpFog",
        session=FakeSession(),
        browser_fallback=False,
    )
    assert item.book_id == "MP_WXS_3243948299"
    assert item.method == "html-biz"


def test_parse_current_mp_chapters_payload():
    payload = {
        "data": [
            {
                "reviewId": "review-new-1",
                "title": "当前接口文章",
                "createTime": 1710000000,
                "mpInfo": {
                    "title": "当前接口文章",
                    "content": "当前接口摘要",
                    "doc_url": "https://mp.weixin.qq.com/s/current-token",
                    "pic_url": "https://example.com/cover.jpg",
                    "mp_name": "当前公众号",
                    "time": 1710000001,
                    "originalId": "orig-1",
                },
            }
        ],
        "synckey": 123,
    }
    articles = parse_articles_payload(payload, "MP_WXS_3911685025")
    assert len(articles) == 1
    assert articles[0].review_id == "review-new-1"
    assert articles[0].url == "https://mp.weixin.qq.com/s/current-token"
    assert articles[0].author == "当前公众号"
    assert articles[0].publish_at == 1710000001


def test_current_mp_chapters_initial_request_uses_synckey_without_offset():
    from wechat_mp_fetcher import WeReadMobileClient

    class FakeResponse:
        status_code = 200
        ok = True
        text = '{"data":[]}'
        def json(self):
            return {"data": []}

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.calls = []
        def get(self, url, *, params, timeout):
            self.calls.append((url, dict(params), timeout))
            return FakeResponse()

    client = WeReadMobileClient("token", "123")
    fake = FakeSession()
    client.session = fake
    assert client.get_articles("MP_WXS_3911685025", count=20, synckey=0) == []
    url, params, _ = fake.calls[0]
    assert url.endswith("/mp/chapters")
    assert params == {"bookId": "MP_WXS_3911685025", "count": 20, "synckey": 0}
    assert "offset" not in params


def test_current_mp_chapters_paging_uses_offset_without_synckey():
    from wechat_mp_fetcher import WeReadMobileClient

    class FakeResponse:
        status_code = 200
        ok = True
        text = '{"data":[]}'
        def json(self):
            return {"data": []}

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.calls = []
        def get(self, url, *, params, timeout):
            self.calls.append((url, dict(params), timeout))
            return FakeResponse()

    client = WeReadMobileClient("token", "123")
    fake = FakeSession()
    client.session = fake
    client.get_articles("MP_WXS_3911685025", count=20, offset=20, synckey=999)
    _, params, _ = fake.calls[0]
    assert params == {"bookId": "MP_WXS_3911685025", "count": 20, "offset": 20}
    assert "synckey" not in params


def test_http_499_includes_body_in_diagnostic():
    import pytest
    from wechat_mp_fetcher import FetcherError, WeReadMobileClient

    class FakeResponse:
        status_code = 499
        ok = False
        text = "ERR"
        def json(self):
            raise ValueError("not json")

    class FakeSession:
        def __init__(self):
            self.headers = {}
        def get(self, url, *, params, timeout):
            return FakeResponse()

    client = WeReadMobileClient("token", "123")
    client.session = FakeSession()
    with pytest.raises(FetcherError) as exc:
        client.get_articles("MP_WXS_3911685025")
    message = str(exc.value)
    assert "HTTP 499" in message
    assert "ERR" in message
    assert "/mp/chapters" in message


def test_review_single_resolves_doc_url():
    from wechat_mp_fetcher import WeReadMobileClient

    class FakeResponse:
        status_code = 200
        ok = True
        text = '{}'
        def json(self):
            return {
                "review": {
                    "reviewId": "r-url-1",
                    "mpInfo": {"doc_url": "https://mp.weixin.qq.com/s/url-token"},
                }
            }

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.calls = []
        def get(self, url, *, params, timeout):
            self.calls.append((url, dict(params), timeout))
            return FakeResponse()

    client = WeReadMobileClient("token", "123")
    fake = FakeSession()
    client.session = fake
    assert client.resolve_article_url("r-url-1") == "https://mp.weixin.qq.com/s/url-token"
    url, params, _ = fake.calls[0]
    assert url.endswith("/review/single")
    assert params["reviewId"] == "r-url-1"
    assert params["synckey"] == 0


def test_resync_does_not_wipe_backfilled_url(tmp_path):
    conn = open_db(tmp_path / "db.sqlite")
    save_article(conn, Article("r-1", "MP_WXS_1", "标题", publish_at=1700000000, url="https://mp.weixin.qq.com/s/backfilled"))
    conn.commit()
    # 模拟同步接口返回的文章：不带 url（同步接口本身不提供原文链接）。
    save_article(conn, Article("r-1", "MP_WXS_1", "标题", publish_at=1700000000))
    conn.commit()
    row = conn.execute("SELECT url FROM articles WHERE review_id='r-1'").fetchone()
    assert row[0] == "https://mp.weixin.qq.com/s/backfilled"
