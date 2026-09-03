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
MAX_NOTIFY_LIMIT = 15  # 15件まで許可（16件以上は自動でLINE通知をスキップしてDBのみ更新）
CAROUSEL_CHUNK_SIZE = 5  # カルーセル1通知あたりの最大商品数

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
DEFAULT_IMAGE_URL = "https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop"

# 6ジャンルデザイン設定
GENRE_CONFIG = [
    {'key': 'お知らせ', 'keywords': ['感謝祭', 'ファン感謝', 'キャンセル待ち'], 'category': '【お知らせ】', 'color': '#D32F2F'}, # レッド
    {'key': '予約', 'keywords': ['ご予約', '予約'], 'category': '【ご予約】', 'color': '#FF5722'},                # オレンジ
    {'key': '限定', 'keywords': ['期間限定', 'sale', 'セール'], 'category': '【期間限定】', 'color': '#8E24AA'}, # パープル
    {'key': '新色', 'keywords': ['新色'], 'category': '【新色入荷】', 'color': '#EC407A'},              # ピンク
    {'key': '再入荷', 'keywords': ['再入荷'], 'category': '【再入荷】', 'color': '#1E88E5'},              # ブルー
    {'key': '入荷', 'keywords': ['入荷'], 'category': '【新着入荷】', 'color': '#1DB446'},              # グリーン
]
DEFAULT_GENRE = {'category': '【新着更新】', 'color': '#607D8B'}


def init_db():
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
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}")
    count = cursor.fetchone()[0]
    conn.close()
    return count == 0


def clean_title(title_text):
    if not title_text:
        return "新着入荷商品"
    text = re.sub(r'^\d{1,2}/\d{1,2}\s*', '', title_text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\[(New Arrivals|再入荷|新色|ご予約|NEW)\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:100]


def force_https_url(url):
    """壊れたURL（https://www.https://...等）を自動修正する堅牢ロジック"""
    if not url:
        return TARGET_URL
    full_url = url.strip()

    # サイト側のミスによる壊れたURLの修復処理
    pids = re.findall(r'pid=(\d+)', full_url)
    if pids and ('https://www.https://' in full_url or full_url.count('http') > 1):
        valid_pid = pids[-1]  # 正確な末尾のpidを取得
        return f"https://www.area-island.com/?pid={valid_pid}"

    if full_url.startswith("http://"):
        return full_url.replace("http://", "https://", 1)
    if not full_url.startswith("http"):
        return urljoin("https://www.area-island.com/", full_url)
    return full_url


def classify_genre(text):
    text_lower = text.lower()
    if any(kw in text_lower for kw in ['感謝祭', 'ファン感謝', 'キャンセル待ち']):
        return 'お知らせ'
    elif '予約' in text_lower:
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
    for g in GENRE_CONFIG:
        if g['key'] == genre_key:
            return g
    return DEFAULT_GENRE


def extract_items_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    raw_items = []
    
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if not href or href.startswith('javascript:') or 'gid=' in href:
            continue
            
        parent = a_tag.parent
        if not parent:
            continue
            
        parent_html = str(parent)
        parent_html = re.sub(r'<br\s*/?>', '【BR】', parent_html, flags=re.IGNORECASE)
        parent_html = parent_html.replace('\n', '【BR】').replace('\r', '')
        
        lines_html = parent_html.split('【BR】')
        
        a_tag_str = str(a_tag)
        target_line_html = ""
        for line in lines_html:
            if a_tag_str in line:
                target_line_html = line
                break
                
        if not target_line_html:
            target_line_html = a_tag_str

        full_text = re.sub(r'<[^>]+>', ' ', target_line_html)
        full_text = re.sub(r'\s+', ' ', full_text).strip()

        if len(full_text) <= 3 or 'トーナメント' in full_text or 'お届け遅延' in full_text:
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
                'url': item_url,
                'image_url': DEFAULT_IMAGE_URL
            })
            
    return raw_items


def create_flex_carousel(items_chunk):
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
                            "label": "詳細を見る",
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
    """5件ずつのブロックに区切ってLINE送信（上限エラー判定を追加）"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("エラー: LINEのアクセス情報が設定されていません。")
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    chunks = [items[i:i + CAROUSEL_CHUNK_SIZE] for i in range(0, len(items), CAROUSEL_CHUNK_SIZE)]
    for chunk in chunks:
        payload = {
            "to": LINE_USER_ID,
            "messages": [create_flex_carousel(chunk)]
        }
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        
        # エラー発生時の判定
        if res.status_code != 200:
            res_text = res.text.lower()
            if res.status_code in [400, 429] and any(kw in res_text for kw in ['limit', 'quota', 'exceeded']):
                print("[ERROR] 今月分のLINE通知上限（200通）に到達しました。")
            else:
                print(f"[ERROR] LINE送信失敗 ({res.status_code}): {res.text}")
            return False

    return True


def save_items(items):
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

    raw_items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        raw_items = extract_items_from_html(page.content())

        if not raw_items:
            print("有効な入荷情報が検出されませんでした。")
            browser.close()
            return

        if first_run:
            save_items(raw_items)
            print("【初回起動検出】現在の全商品をDBに初期登録しました（通知は送信されません）。")
            browser.close()
            return

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        new_items = []
        for item in raw_items:
            cursor.execute(f"SELECT 1 FROM {TABLE_NAME} WHERE item_id = ?", (item['item_id'],))
            if not cursor.fetchone():
                new_items.append(item)
        conn.close()

        if not new_items:
            print("新しい更新はありませんでした。")
            browser.close()
            return

        # ガードレール: 15件超過時の自動抑止（連投防止）
        if len(new_items) > MAX_NOTIFY_LIMIT:
            print(f"【大量通知ストッパー作動】{len(new_items)}件の新着情報を検出。")
            print(f"設定上限（{MAX_NOTIFY_LIMIT}件）を超えたため、LINE通知をキャンセルしてDBのみ更新します。")
            save_items(new_items)
            browser.close()
            return

        # 未通知商品のみ詳細ページへアクセス
        print(f"{len(new_items)}件の新着を検知。画像を取得します...")
        for item in new_items:
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
            
        browser.close()

    # LINE送信（成功時のみDB保存）
    if send_line_flex_messages(new_items):
        save_items(new_items)
        print(f"{len(new_items)}件の新着入荷情報をLINEに送信し、DBを更新しました。")


if __name__ == "__main__":
    main()
