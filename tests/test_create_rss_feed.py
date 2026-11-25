import datetime
import io
import json
import unittest
import urllib.error
from unittest import mock

import create_rss_feed as crf

UTC = datetime.timezone.utc
NOW = datetime.datetime(2025, 6, 28, 6, 44, 13, tzinfo=UTC)


def article(title="t", day=27, thumbnail=None, link=None):
    link = link or f"https://example.com/{title}"
    return {
        "title": title,
        "link": link,
        "guid": link,
        "pub_date": datetime.datetime(2025, 6, day, 5, 12, 40, tzinfo=UTC),
        "thumbnail": thumbnail,
    }


def render(articles):
    tree = crf.build_rss(articles, NOW)
    buf = io.BytesIO()
    tree.write(buf, xml_declaration=True, encoding="UTF-8")
    return buf.getvalue()


class ExtractPublishedTimeTest(unittest.TestCase):
    def test_present(self):
        html = '<html><head><meta property="article:published_time" content="2025-06-27T05:12:40Z"></head></html>'
        self.assertEqual(crf.extract_published_time(html), "2025-06-27T05:12:40Z")

    def test_absent(self):
        self.assertIsNone(crf.extract_published_time("<html><head></head></html>"))

    def test_empty_content(self):
        html = '<meta property="article:published_time" content="">'
        self.assertIsNone(crf.extract_published_time(html))

    def test_mixed_meta(self):
        html = (
            '<meta property="og:title" content="x">'
            '<meta name="description" content="y">'
            '<meta property="article:published_time" content="2025-01-02T03:04:05+09:00">'
            '<meta property="article:modified_time" content="2026-01-01T00:00:00Z">'
        )
        self.assertEqual(crf.extract_published_time(html), "2025-01-02T03:04:05+09:00")


class ParseDatetimeTest(unittest.TestCase):
    def test_z_suffix(self):
        dt = crf.parse_published_time("2025-06-27T05:12:40Z")
        self.assertEqual(dt, datetime.datetime(2025, 6, 27, 5, 12, 40, tzinfo=UTC))
        self.assertIsNotNone(dt.tzinfo)

    def test_offset(self):
        dt = crf.parse_published_time("2025-06-27T14:12:40+09:00")
        self.assertEqual(dt, datetime.datetime(2025, 6, 27, 5, 12, 40, tzinfo=UTC))
        self.assertEqual(dt.utcoffset(), datetime.timedelta(hours=9))


class BuildRssTest(unittest.TestCase):
    def test_declaration_and_root(self):
        data = render([article()])
        self.assertTrue(data.startswith(b"<?xml version='1.0' encoding='UTF-8'?>"))
        self.assertNotIn(b"generator", data)
        self.assertNotIn(b"xmlns", data)

    def test_channel(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(render([article()]))
        self.assertEqual(root.tag, "rss")
        self.assertEqual(root.get("version"), "2.0")
        channel = root.find("channel")
        children = [c for c in channel if c.tag != "item"]
        self.assertEqual(
            [(c.tag, c.text) for c in children],
            [
                ("title", "Hatena Dev Entries"),
                ("link", "https://hatena.blog/dev/entries"),
                ("description", "最新のHatena Devブログ記事"),
                ("docs", "http://www.rssboard.org/rss-specification"),
                ("language", "ja"),
                ("lastBuildDate", "Sat, 28 Jun 2025 06:44:13 +0000"),
            ],
        )

    def test_item_order_and_values(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(render([article("a", thumbnail="https://img/x.png")]))
        item = root.find("channel/item")
        self.assertEqual([c.tag for c in item], ["title", "link", "guid", "enclosure", "pubDate"])
        self.assertEqual(item.find("link").text, "https://example.com/a")
        guid = item.find("guid")
        self.assertEqual(guid.text, "https://example.com/a")
        self.assertEqual(guid.get("isPermaLink"), "true")
        self.assertEqual(item.find("pubDate").text, "Fri, 27 Jun 2025 05:12:40 +0000")

    def test_enclosure_types(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(render([
            article("p", day=3, thumbnail="https://img/x.png"),
            article("j", day=2, thumbnail="https://img/x.jpg"),
            article("n", day=1, thumbnail=None),
        ]))
        items = root.findall("channel/item")
        enc = items[0].find("enclosure")
        self.assertEqual(enc.attrib, {"url": "https://img/x.png", "length": "0", "type": "image/png"})
        enc = items[1].find("enclosure")
        self.assertEqual(enc.attrib, {"url": "https://img/x.jpg", "length": "0", "type": "image/jpeg"})
        self.assertIsNone(items[2].find("enclosure"))

    def test_escaping_and_japanese(self):
        import xml.etree.ElementTree as ET
        title = "日本語 & <タグ> \"q\""
        data = render([article(title)])
        self.assertIn("日本語 &amp; &lt;タグ&gt;".encode("utf-8"), data)
        root = ET.fromstring(data)
        self.assertEqual(root.find("channel/item/title").text, title)

    def test_pubdate_offset_formatting(self):
        import xml.etree.ElementTree as ET
        a = article()
        a["pub_date"] = datetime.datetime(2025, 6, 27, 14, 12, 40, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
        root = ET.fromstring(render([a]))
        self.assertEqual(root.find("channel/item/pubDate").text, "Fri, 27 Jun 2025 14:12:40 +0900")


class SelectLatestTest(unittest.TestCase):
    def test_sorted_by_datetime_not_weekday_name(self):
        # 2025-06-27 は Fri、06-28 は Sat、06-29 は Sun、06-30 は Mon。
        # 曜日名の文字列順だと Sun > Sat > Mon > Fri になり実際の順序と食い違う。
        arts = [article("fri", 27), article("mon", 30), article("sat", 28), article("sun", 29)]
        result = crf.select_latest(arts)
        self.assertEqual([a["title"] for a in result], ["mon", "sun", "sat", "fri"])

    def test_truncates_to_max_items(self):
        arts = [
            {**article(f"a{i}"), "pub_date": datetime.datetime(2025, 1, 1, tzinfo=UTC) + datetime.timedelta(hours=i)}
            for i in range(40)
        ]
        result = crf.select_latest(arts)
        self.assertEqual(len(result), crf.MAX_ITEMS)
        self.assertEqual(result[0]["title"], "a39")
        self.assertEqual(result[-1]["title"], "a10")


class FakeResponse:
    def __init__(self, body, charset=None):
        self._body = body
        self.headers = mock.Mock()
        self.headers.get_content_charset.return_value = charset

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FetchArticlesTest(unittest.TestCase):
    def test_skips_404_and_other_errors(self):
        entries = [
            {"id": 1, "title": "ok", "url": "https://b/ok", "created": "", "imageUrl": "https://i/a.png"},
            {"id": 2, "title": "gone", "url": "https://b/gone", "created": "", "imageUrl": None},
            {"id": 3, "title": "boom", "url": "https://b/boom", "created": "", "imageUrl": None},
        ]
        api = json.dumps({"data": {"recentEntries": {"entries": entries}}}).encode()
        page = '<meta property="article:published_time" content="2025-06-27T05:12:40Z">'.encode()

        def fake_urlopen(req, timeout=None):
            self.assertEqual(timeout, 30)
            url = req if isinstance(req, str) else req.full_url
            if url.endswith("/api/graphql"):
                self.assertEqual(req.get_method(), "POST")
                self.assertEqual(req.get_header("Content-type"), "application/json")
                return FakeResponse(api, "utf-8")
            if url.endswith("/ok"):
                return FakeResponse(page)
            if url.endswith("/gone"):
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())
            raise ValueError("boom")

        with mock.patch("create_rss_feed.urllib.request.urlopen", side_effect=fake_urlopen), \
                mock.patch("builtins.print") as pr:
            result = crf.fetch_articles(0, 20)

        self.assertEqual([a["title"] for a in result], ["ok"])
        self.assertEqual(result[0]["pub_date"], datetime.datetime(2025, 6, 27, 5, 12, 40, tzinfo=UTC))
        self.assertEqual(result[0]["thumbnail"], "https://i/a.png")
        self.assertEqual(pr.call_count, 2)

    def test_non_404_http_error_propagates(self):
        # 現行実装どおり 404 以外の HTTPError は except Exception に
        # 捕まらず呼び出し元まで伝播する。
        entries = [{"id": 1, "title": "x", "url": "https://b/x", "created": "", "imageUrl": None}]
        api = json.dumps({"data": {"recentEntries": {"entries": entries}}}).encode()

        def fake_urlopen(req, timeout=None):
            if req.full_url.endswith("/api/graphql"):
                return FakeResponse(api, "utf-8")
            raise urllib.error.HTTPError(req.full_url, 500, "err", {}, io.BytesIO())

        with mock.patch("create_rss_feed.urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(urllib.error.HTTPError):
                crf.fetch_articles(0, 20)


if __name__ == "__main__":
    unittest.main()
