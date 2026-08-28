import os
import re
import hashlib
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 基本設定 ---
TARGET_URL = "https://www.area-island.com/"
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")
DEFAULT_IMAGE_URL = "https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop"

# 6ジャンルデザイン設定（「お知らせ」を追加）
GENRE_CONFIG = [
    {'key': 'お知らせ', 'keywords': ['感謝祭', 'イベント', 'お知らせ', '受付', 'キャンセル待ち'], 'category': '【お知らせ】', 'color': '#D32F2F'}, # レッド
    {'key': '予約', 'keywords': ['ご予約', '予約'], 'category': '【ご予約】', 'color': '#FF5722'},                # オレンジ
    {'key': '限定', 'keywords': ['期間限定', 'sale', 'セール'], 'category': '【期間限定】', 'color': '#8E24AA'}, # パープル
    {'key': '新色', 'keywords': ['新色'], 'category': '【新色入荷】', 'color': '#EC407A'},              # ピンク
    {'key': '再入荷', 'keywords': ['再入荷'], 'category': '【再入荷】', 'color': '#1E88E5'},              # ブルー
    {'key': '入荷', 'keywords': ['入荷'], 'category': '【新着入荷】', 'color': '#1DB446'},              # グリーン
]
DEFAULT_GENRE = {'category': '【新着更新】', 'color': '#607D8B'}


def clean_title(title_text):
    if not title_text:
        return "新着入荷商品"
    text = re.sub(r'^\d{1,2}/\d{1,2}\s*', '', title_text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\[(New Arrivals|再入荷|新色|ご予約|NEW)\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:100]


def force_https_url(url):
    if not url:
        return TARGET_URL
    full_url = url.strip()
    if full_url.startswith("http://"):
        return full_url.replace("http://", "https://", 1)
    if not full_url.startswith("http"):
        return urljoin("https://www.area-island.com/", full_url)
    return full_url


def classify_genre(text):
    text_lower = text.lower()
    # イベント・お知らせ系を最優先で判定
    if any(kw in text_lower for kw in ['感謝祭', 'イベント', 'お知らせ', '受付', 'キャンセル待ち']):
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
    """HTMLを改行で完全分割し、イベント・お知らせ枠を含めて安全抽出"""
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

        # 不要な一般バナーのみ除外
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


def fetch_test_items():
    """テスト用：イベント告知＋最新商品を抽出"""
    items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        
        raw_items = extract_items_from_html(page.content())

        # お知らせ枠（感謝祭等）＋最新商品を最大5件ピックアップ
        filtered_items = [i for i in raw_items if i['genre_key'] == 'お知らせ']
        for i in raw_items:
            if i not in filtered_items:
                filtered_items.append(i)
            if len(filtered_items) >= 5:
                break

        for item in filtered_items:
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
                print(f"詳細ページ解析エラー: {e}")
            item['image_url'] = force_https_url(img_url)
            items.append(item)

        browser.close()
    return items


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
        "altText": f"【イベント検知テスト】通知（{len(items_chunk)}件）",
        "contents": {
            "type": "carousel",
            "contents": bubbles
        }
    }


def main():
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("エラー: LINE情報が設定されていません。")
        return

    print("【テスト専用モード】ヴァルケインファン感謝祭を含むテスト通知を送信します...")
    items = fetch_test_items()

    if not items:
        print("対象が見つかりませんでした。")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    payload = {
        "to": LINE_USER_ID,
        "messages": [create_flex_carousel(items)]
    }

    res = requests.post(url, headers=headers, json=payload, timeout=10)
    if res.status_code == 200:
        print("LINEへテスト通知を送信しました。")
    else:
        print(f"LINE送信エラー: {res.status_code} - {res.text}")


if __name__ == "__main__":
    main()
