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
MAX_NOTIFY_LIMIT = 5  # 1回の実行で未通知がこの件数を超えた場合、通知を全キャンセルしてDBのみ更新

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
DEFAULT_IMAGE_URL = "https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop"

# 5ジャンルデザイン設定
GENRE_CONFIG = [
    {'key': '予約', 'keywords': ['ご予約', '予約'], 'category': '【ご予約】', 'color': '#FF5722'},                # オレンジ
    {'key': '限定', 'keywords': ['期間限定', 'sale', 'セール'], 'category': '【期間限定】', 'color': '#8E24AA'}, # パープル
    {'key': '新色', 'keywords': ['新色'], 'category': '【新色入荷】', 'color': '#EC407A'},              # ピンク
    {'key': '再入荷', 'keywords': ['再入荷'], 'category': '【再入荷】', 'color': '#1E88E5'},              # ブルー
    {'key': '入荷', 'keywords': ['入荷'], 'category': '【新着入荷】', 'color': '#1DB446'},              # グリーン
]
DEFAULT_GENRE = {'category': '【新着更新】', 'color': '#607D8B'}


def init_db():
    """データベース初期化"""
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
    """DBが空（初回実行）判定"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    count = cursor.fetchone()[0]
    conn.close()
    return count == 0


def clean_title(title_text):
    """タイトルのクレンジング（日付や不要タグの除去）"""
    if not title_text:
        return "新着入荷商品"
    text = re.sub(r'^\d{1,2}/\d{1,2}\s*', '', title_text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\[(New Arrivals|再入荷|新色|ご予約|NEW)\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:100]


def force_https_url(url):
    """すべてのURLをLINE API規格（HTTPS）に安全強制変換"""
    if not url:
        return TARGET_URL
    full_url = url.strip()
    if full_url.startswith("http://"):
        return full_url.replace("http://", "https://", 1)
    if not full_url.startswith("http"):
        return urljoin("https://www.area-island.com/", full_url)
    return full_url


def classify_genre(text):
    """文字列から5ジャンルを優先度順に判定"""
    text_lower = text.lower()
    if '予約' in text_lower:
        return '予約'
    elif any(kw in text_lower for kw in ['期間限定', 'sale', 'セール']):
        return '限定'
    elif '新色' in text_lower:
        return '新色'
    elif '再入荷' in text_lower:
        return '再入荷'
    elif '入荷' in text_lower:
        return '入荷'
    return 'その他'


def get_genre_config_by_key(genre_key):
    """ジャンルキーから配色設定を取得"""
    for g in GENRE_CONFIG:
        if g['key'] == genre_key:
            return g
    return DEFAULT_GENRE


def get_surrounding_text(a_tag):
    """
    【新設】<a>タグの前後にあるテキストを安全に取得。
    他のリンクや改行にぶつかったらストップし、他商品のテキスト混同を100%防止する。
    """
    stop_tags = ['br', 'p', 'div', 'table', 'tr', 'td', 'a', 'li', 'ul', 'h1', 'h2', 'h3']
    
    prev_text = []
    for sibling in a_tag.previous_siblings:
        if sibling.name in stop_tags:
            break
        if isinstance(sibling, str):
            txt = sibling.strip()
            if txt:
                prev_text.insert(0, txt)
        else:
            txt = sibling.get_text(strip=True)
            if txt:
                prev_text.insert(0, txt)
                
    next_text = []
    for sibling in a_tag.next_siblings:
        if sibling.name in stop_tags:
            break
        if isinstance(sibling, str):
            txt = sibling.strip()
            if txt:
                next_text.append(txt)
        else:
            txt = sibling.get_text(strip=True)
            if txt:
                next_text.append(txt)
                
    a_text = a_tag.get_text(strip=True)
    full_text = " ".join(prev_text) + " " + a_text + " " + " ".join(next_text)
    full_text = re.sub(r'\s+', ' ', full_text).strip()
    return full_text, a_text


def fetch_site_items():
    """Webサイトから全入荷情報を抽出し、各商品詳細ページから本物の画像を特定"""
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        soup = BeautifulSoup(page.content(), 'html.parser')

        raw_items = []
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if not href or href.startswith('javascript:'):
                continue

            full_text, a_text = get_surrounding_text(a_tag)

            # バナー画像のみのリンクや短すぎるテキストを除外
            if len(a_text) <= 3 or 'トーナメント' in full_text or 'お届け遅延' in full_text:
                continue

            genre_key = classify_genre(full_text)
            if genre_key == 'その他':
                continue

            item_url = force_https_url(urljoin(TARGET_URL, href))
            cleaned_title = clean_title(full_text)
            item_id = hashlib.md5(f"{item_url}_{cleaned_title}".encode('utf-8')).hexdigest()

            if not any(i['item_id'] == item_id for i in raw_items):
                raw_items.append({
                    'item_id': item_id,
                    'genre_key': genre_key,
                    'title': cleaned_title,
                    'raw_title': full_text,
                    'url': item_url
                })

        # 各商品の詳細ページへ移動し本物の画像を抽出
        for item in raw_items:
            img_url = DEFAULT_IMAGE_URL
            try:
                page.goto(item['url'], wait_until="domcontentloaded", timeout=20000)
                detail_soup = BeautifulSoup(page.content(), 'html.parser')

                for img in detail_soup.find_all('img', src=True):
                    src = img['src']
                    if any(ex in src.lower() for ex in ['blank.gif', 'spacer.gif', 'logo', 'banner', 'btn', 'cart', 'header', 'footer']):
                        continue

                    img_url = force_https_url(urljoin(item['url'], src))
                    if any(kw in src.lower() for kw in ['upload', 'save_image', 'goods', 'product']):
                        break
            except Exception as e:
                print(f"詳細ページの画像解析エラー ({item['url']}): {e}")

            item['image_url'] = force_https_url(img_url)
            items.append(item)

        browser.close()
    return items


def create_flex_carousel(items_chunk):
    """LINE Flex Message Carousel (最大10件/メッセージ) の構築"""
    bubbles = []
    for item in items_chunk:
        genre = get_genre_config_by_key(item['genre_key'])

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
                        "text": genre['category'],
                        "weight": "bold",
                        "size": "xs",
                        "color": genre['color']
                    },
                    {
                        "type": "text",
                        "text": item['title'],
                        "weight": "bold",
                        "size": "md",
                        "wrap": True,
                        "maxLines": 3,
                        "margin": "xs"
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
                        "color": genre['color']
                    }
                ]
            }
        }
        bubbles.append(bubble)

    return {
        "type": "flex",
        "altText": f"【越谷トラウトアイランド】新着更新（{len(items_chunk)}件）",
        "contents": {
            "type": "carousel",
            "contents": bubbles
        }
    }


def send_line_flex_messages(items):
    """LINE API経由で10件単位にパッキングして送信"""
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
    """アイテムを既読としてDB保存"""
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

    # ガードレール 1: 初回起動時は全件DB化し通知を自動スキップ（大量通知防止）
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

    # ガードレール 2: 大量通知ストッパー（MAX_LIMIT超過時の自動抑止）
    if len(new_items) > MAX_NOTIFY_LIMIT:
        print(f"【大量通知ストッパー作動】{len(new_items)}件の未通知情報を検出。")
        print(f"設定上限（{MAX_NOTIFY_LIMIT}件）を超えたため、LINE通知をキャンセルしてDBのみ更新します。")
        save_items(new_items)
        return

    # 通常通知処理
    if send_line_flex_messages(new_items):
        save_items(new_items)
        print(f"{len(new_items)}件の新着入荷情報をLINEに送信しました。")


if __name__ == "__main__":
    main()
