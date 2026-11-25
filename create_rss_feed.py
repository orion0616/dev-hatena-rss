import datetime
import email.utils
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

# 設定
TARGET_BASE_URL = "https://hatena.blog/dev"
RSS_OUTPUT_FILE = "hatena_dev_entries.xml"
MAX_ITEMS = 30
REQUEST_TIMEOUT = 30


class _PublishedTimeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.published_time = None
        self._matched = False

    def handle_starttag(self, tag, attrs):
        if tag != "meta" or self._matched:
            return
        attrs = dict(attrs)
        if attrs.get("property") == "article:published_time":
            # 最初に一致した meta だけを見る。content が空なら後続は採用しない。
            self._matched = True
            self.published_time = attrs.get("content") or None


def extract_published_time(html):
    """HTML 中の `article:published_time` meta の content を返す。無い・空なら None。"""
    parser = _PublishedTimeParser()
    parser.feed(html)
    return parser.published_time


def parse_published_time(value):
    """ISO 8601 形式の日時文字列(末尾 Z 可)をタイムゾーン付き datetime に変換する。"""
    dt = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _open(request):
    """リクエストを送り、Content-Type の charset(無ければ UTF-8)でデコードした本文を返す。"""
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def fetch_articles(skip=0, limit=20):
    query = """
    query EntriesQuery($skip: Int, $limit: Int!) {
      recentEntries(skip: $skip, limit: $limit) {
        entries {
          id
          title
          url
          created
          imageUrl
        }
        hasNextPage
      }
    }
    """

    payload = {
        "query": query,
        "operationName": "EntriesQuery",
        "variables": {
            "skip": skip,
            "limit": limit
        }
    }

    request = urllib.request.Request(
        TARGET_BASE_URL + "/api/graphql",
        data=json.dumps(payload).encode("utf-8"),
        headers={'Content-Type': 'application/json'},
        method="POST",
    )
    data = json.loads(_open(request))
    articles = []

    # 記事リストの解析
    recent_entries = data.get("data", {}).get("recentEntries", {}).get("entries", [])
    for entry in recent_entries:
        try:
            # 各記事のページを取得して公開日時を取得
            html = _open(urllib.request.Request(entry['url']))

            pub_date_str = extract_published_time(html)
            if pub_date_str:
                pub_date = parse_published_time(pub_date_str)
            else:
                # 公開日時が取得できない場合は現在日時を使用
                pub_date = datetime.datetime.now(datetime.timezone.utc)

            articles.append({
                'title': entry['title'],
                'link': entry['url'],
                'guid': entry['url'],
                'pub_date': pub_date,
                'thumbnail': entry.get('imageUrl')
            })
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"警告: 記事が見つかりません: {entry['url']}")
                continue
            raise
        except Exception as e:
            print(f"警告: 記事の処理中にエラーが発生しました: {entry['url']} - {str(e)}")
            continue

    return articles


def select_latest(articles):
    """公開日時の新しい順に並べ、上位 MAX_ITEMS 件を返す。"""
    return sorted(articles, key=lambda x: x['pub_date'], reverse=True)[:MAX_ITEMS]


_XML_INVALID_CHARS = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def _clean(text):
    # XML 1.0 で禁止された文字が1つでもあるとフィード全体がパース不能になるため、例外にせず取り除く。
    return _XML_INVALID_CHARS.sub('', text)


def build_rss(articles, now):
    """記事リストを渡された順のまま RSS 2.0 の ElementTree にする。now は lastBuildDate に使う。"""
    rss = ET.Element('rss', version='2.0')
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = 'Hatena Dev Entries'
    ET.SubElement(channel, 'link').text = TARGET_BASE_URL + "/entries"
    ET.SubElement(channel, 'description').text = '最新のHatena Devブログ記事'
    ET.SubElement(channel, 'docs').text = 'http://www.rssboard.org/rss-specification'
    ET.SubElement(channel, 'language').text = 'ja'
    ET.SubElement(channel, 'lastBuildDate').text = email.utils.format_datetime(now)

    for article in articles:
        item = ET.SubElement(channel, 'item')
        ET.SubElement(item, 'title').text = _clean(article['title'])
        ET.SubElement(item, 'link').text = _clean(article['link'])
        guid = ET.SubElement(item, 'guid', isPermaLink='true')
        guid.text = _clean(article['guid'])

        # サムネイル画像の追加
        if article['thumbnail']:
            mime_type = 'image/png' if article['thumbnail'].endswith('.png') else 'image/jpeg'
            ET.SubElement(item, 'enclosure', url=_clean(article['thumbnail']), length='0', type=mime_type)

        ET.SubElement(item, 'pubDate').text = email.utils.format_datetime(article['pub_date'])

    tree = ET.ElementTree(rss)
    ET.indent(tree, space='  ')
    return tree


def create_rss_feed(articles):
    now = datetime.datetime.now(datetime.timezone.utc)
    tree = build_rss(articles, now)
    tree.write(RSS_OUTPUT_FILE, xml_declaration=True, encoding="UTF-8")
    print(f"RSSフィードが {RSS_OUTPUT_FILE} に生成されました。")

def main():
    try:
        articles = []
        page = 0
        while len(articles) < MAX_ITEMS:
            new_articles = fetch_articles(page*20,20)
            articles.extend(new_articles)
            page += 1

        # 最新の MAX_ITEMS 件を保持
        articles = select_latest(articles)

        print(f"最新の記事 {len(articles)} 件をRSSフィードに保持します。")
        create_rss_feed(articles)
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        # 必要に応じて通知機能を追加
        raise  # エラーを再スローしてワークフローが失敗と認識するように

if __name__ == "__main__":
    main()

