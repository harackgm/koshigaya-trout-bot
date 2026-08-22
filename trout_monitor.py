import os
import re
import sqlite3
import hashlib
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 基本設定 ---
TARGET_URL = "https://www.area-island.com/"
DB_FILE = "shop_data.db"
TABLE_NAME = "notified_items"

# --- ガードレール設定（安全装置） ---
MAX_NOTIFY_LIMIT = 5  # 一度の実行で未通知がこの件数を超えた場合、通知を自動停止してDBのみ更新

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
DEFAULT_IMAGE_URL = "https://via.placeholder.com/300x200.png?text=No+Image"


def init_db():
    """データベースの初期化"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            item_id TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            image_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def is_db_empty():
    """DBが空（初回実行）かどうかを判定"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    count = cursor.fetchone()[0]
    conn.close()
    return count == 0


def clean_title(title_text):
    """タイトルの不要タグ・マーク除去"""
    if not title_text:
        return "新着入荷商品"
    text = re.sub(r'<[^>]+>', '', title_text)
    text = re.sub(r'\[(New Arrivals|再入荷|新色|ご予約|NEW)\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:100]


def clean_url(base_url, rel_url):
    """URLの表記揺れ防止と絶対パス化"""
    if not rel_url:
        return base_url
    full_url = urljoin(base_url, rel_url)
    return full_url.rstrip('/')


def clean_image_url(base_url, img_element):
    """画像URLの検証と取得"""
    if not img_element:
        return DEFAULT_IMAGE_URL
    src = (
        img_element.get('data-src') or 
        img_element.get('data-original') or 
        img_element.get('src')
    )
    if not src or 'blank.gif' in src or 'spacer.gif' in src:
        return DEFAULT_IMAGE_URL
    return urljoin(base_url, src)


def fetch_site_items():
    """Webサイトから入荷情報を取得"""
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        html_content = page.content()
        browser.close()

    soup = BeautifulSoup(html_content, 'html.parser')
    keywords = ['入荷', '再入荷', '新色', 'ご予約', '限定']

    for a_tag in soup.find_all('a', href=True):
        text = a_tag.get_text(strip=True)
        if any(kw in text for kw in keywords) and len(text) > 3:
            item_url = clean_url(TARGET_URL, a_tag['href'])
            cleaned_title = clean_title(text)
            img_tag = a_tag.find('img') or (a_tag.parent.find('img') if a_tag.parent else None)
            img_url = clean_image_url(TARGET_URL, img_tag)

            # URLとタイトルからユニークID生成
            item_id = hashlib.md5(f"{item_url}_{cleaned_title}".encode('utf-8')).hexdigest()

            if not any(i['item_id'] == item_id for i in items):
                items.append({
                    'item_id': item_id,
                    'title': cleaned_title,
                    'url': item_url,
                    'image_url': img_url
                })
    return items


def create_flex_carousel(items_chunk):
    """LINE Flex Message用のデータ構造を作成"""
    bubbles = []
    for item in items_chunk:
        bubble = {
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": item['image_url'],
                "size": "full",
                "aspectRatio": "20:13",
                "aspectMode": "cover"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": item['title'],
                        "weight": "bold",
                        "size": "md",
                        "wrap": True,
                        "maxLines": 3
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "商品詳細を見る",
                            "uri": item['url']
                        },
                        "style": "primary",
                        "color": "#1DB446"
                    }
                ]
            }
        }
        bubbles.append(bubble)

    return {
        "type": "flex",
        "altText": f"【越谷トラウトアイランド】新着入荷（{len(items_chunk)}件）",
        "contents": {
            "type": "carousel",
            "contents": bubbles
        }
    }


def send_line_flex_messages(items):
    """LINE APIへ通知送信（10件単位で送信）"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("エラー: LINEのアクセス情報が設定されていません。")
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    chunks = [items[i:i + 10] for i in range(0, len(items), 10)]
    for chunk in chunks:
        payload = {
            "to": LINE_USER_ID,
            "messages": [create_flex_carousel(chunk)]
        }
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"LINE送信エラー: {res.status_code} - {res.text}")
            return False
    return True


def save_items(items):
    """アイテムをDBに既読保存"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    for item in items:
        cursor.execute(f"""
            INSERT OR IGNORE INTO {TABLE_NAME} (item_id, title, url, image_url)
            VALUES (?, ?, ?, ?)
        """, (item['item_id'], item['title'], item['url'], item['image_url']))
    conn.commit()
    conn.close()


def main():
    init_db()
    first_run = is_db_empty()
    
    current_items = fetch_site_items()
    if not current_items:
        print("有効な入荷情報が検出されませんでした。")
        return

    # ガードレール 1: 初回実行時は全件を既読登録し、LINE通知は完全にスキップ
    if first_run:
        save_items(current_items)
        print("【初回起動検出】現在の入荷情報をDBに初期登録しました（LINE通知は送信されません）。")
        return

    # 未通知アイテムの抽出
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    new_items = []
    for item in current_items:
        cursor.execute(f"SELECT 1 FROM {TABLE_NAME} WHERE item_id = ?", (item['item_id'],))
        if not cursor.fetchone():
            new_items.append(item)
    conn.close()

    if not new_items:
        print("新しい更新はありません。")
        return

    # ガードレール 2: 大量通知ストッパー（MAX_LIMIT超過時の通知キャンセル）
    if len(new_items) > MAX_NOTIFY_LIMIT:
        print(f"【大量通知ストッパー作動】{len(new_items)}件の未通知情報を検出。")
        print(f"設定上限（{MAX_NOTIFY_LIMIT}件）を超えたため、LINE通知をキャンセルしてDBのみ更新します。")
        save_items(new_items)
        return

    # 通常通知処理
    if send_line_flex_messages(new_items):
        save_items(new_items)
        print(f"{len(new_items)}件の新着情報をLINEに送信しました。")


if __name__ == "__main__":
    main()
