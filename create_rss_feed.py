import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import os
import datetime

# 設定
TARGET_BASE_URL = "https://hatena.blog/dev/entries"
RSS_OUTPUT_FILE = "hatena_dev_entries.xml"
MAX_ITEMS = 30


def fetch_articles(url):
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    articles = []
    # 新着記事のリストを探す
    for article_tag in soup.select('div.Entries_columns__GI_fe > div[data-gtm-track-area="entries"] ul > li > div > a.styles_entryLink__DEklK'):
        title = article_tag.get_text(strip=True)
        link = article_tag['href']
        guid = link  # GUIDとしてリンクを使用
        pub_date = datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S %z')  # 現在日時を仮の公開日時として使用
        articles.append({'title': title, 'link': link, 'guid': guid, 'pub_date': pub_date})

    return articles


def create_rss_feed(articles):
    fg = FeedGenerator()
    fg.title('Hatena Dev Entries')
    fg.link(href=TARGET_BASE_URL, rel='alternate')
    fg.description('最新のHatena Devブログ記事')
    fg.language('ja')

    for article in articles[:MAX_ITEMS]:
        fe = fg.add_entry()
        fe.title(article['title'])
        fe.link(href=article['link'])
        fe.pubDate(article['pub_date'])
        fe.guid(article['guid'], permalink=True)

    fg.rss_file(RSS_OUTPUT_FILE, pretty=True)
    print(f"RSSフィードが {RSS_OUTPUT_FILE} に生成されました。")


def main():
    try:
        articles = []
        page = 1
        while len(articles) < MAX_ITEMS:
            url = f"{TARGET_BASE_URL}?page={page}#recent"
            new_articles = fetch_articles(url)
            if not new_articles:
                break
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
