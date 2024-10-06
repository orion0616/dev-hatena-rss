import json
import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import datetime

# 設定
TARGET_BASE_URL = "https://hatena.blog/dev"
RSS_OUTPUT_FILE = "hatena_dev_entries.xml"
MAX_ITEMS = 30

def fetch_articles(skip=0, limit=20):
    headers = {
        'Content-Type': 'application/json',
    }

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

    response = requests.post(TARGET_BASE_URL + "/api/graphql", headers=headers, data=json.dumps(payload))
    response.raise_for_status()

    data = response.json()
    articles = []

    # 記事リストの解析
    recent_entries = data.get("data", {}).get("recentEntries", {}).get("entries", [])
    for entry in recent_entries:
        # 各記事のページを取得して公開日時を取得
        article_response = requests.get(entry['url'])
        article_response.raise_for_status()
        article_soup = BeautifulSoup(article_response.text, 'html.parser')

        pub_date_tag = article_soup.find('meta', property='article:published_time')
        if pub_date_tag and pub_date_tag.get('content'):
            pub_date_unix = int(pub_date_tag['content'])
            pub_date = datetime.datetime.fromtimestamp(pub_date_unix, tz=datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S %z')
        else:
            # 公開日時が取得できない場合は現在日時を使用
            pub_date = datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S %z')

        articles.append({
            'title': entry['title'],
            'link': entry['url'],
            'guid': entry['url'],
            'pub_date': pub_date,
            'thumbnail': entry.get('imageUrl')
        })

    return articles

def create_rss_feed(articles):
    fg = FeedGenerator()
    fg.title('Hatena Dev Entries')
    fg.link(href=TARGET_BASE_URL + "/entries", rel='alternate')
    fg.description('最新のHatena Devブログ記事')
    fg.language('ja')

    for article in articles[:MAX_ITEMS]:
        fe = fg.add_entry()
        fe.title(article['title'])
        fe.link(href=article['link'])
        fe.pubDate(article['pub_date'])
        fe.guid(article['guid'], permalink=True)

        # サムネイル画像の追加
        if article['thumbnail']:
            mime_type = 'image/png' if article['thumbnail'].endswith('.png') else 'image/jpeg'
            fe.enclosure(url=article['thumbnail'], type=mime_type)

    fg.rss_file(RSS_OUTPUT_FILE, pretty=True)
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
        articles = sorted(articles, key=lambda x: x['pub_date'], reverse=True)[:MAX_ITEMS]

        print(f"最新の記事 {len(articles)} 件をRSSフィードに保持します。")
        create_rss_feed(articles)
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        # 必要に応じて通知機能を追加
        raise  # エラーを再スローしてワークフローが失敗と認識するように

if __name__ == "__main__":
    main()
