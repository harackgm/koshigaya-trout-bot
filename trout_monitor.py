import os
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 設定項目 ---
TARGET_URL = "https://www.area-island.com/"
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

DEFAULT_IMAGE_URL = "https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop"

# 5ジャンルデザイン設定
GENRE_CONFIG = [
    {'key': '予約', 'keywords': ['予約'], 'category': '【ご予約】', 'color': '#FF5722'},                # オレンジ
    {'key': '限定', 'keywords': ['期間限定', 'sale', 'セール'], 'category': '【期間限定】', 'color': '#8E24AA'}, # パープル
    {'key': '新色', 'keywords': ['新色'], 'category': '【新色入荷】', 'color': '#EC407A'},              # ピンク
    {'key': '再入荷', 'keywords': ['再入荷'], 'category': '【再入荷】', 'color': '#1E88E5'},              # ブルー
    {'key': '入荷', 'keywords': ['入荷'], 'category': '【新着入荷】', 'color': '#1DB446'},              # グリーン
]
DEFAULT_GENRE = {'category': '【新着更新】', 'color': '#607D8B'}


def clean_title(title_text):
    """タイトルのクレンジング"""
    if not title_text:
        return "新着入荷商品"
    text = re.sub(r'<[^>]+>', '', title_text)
    text = re.sub(r'\[(New Arrivals|再入荷|新色|ご予約|NEW)\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:100]


def clean_url(base_url, rel_url):
    """URLの絶対パス化と正規化"""
    if not rel_url:
        return base_url
    full_url = urljoin(base_url, rel_url)
    return full_url.rstrip('/')


def classify_genre(title_text):
    """タイトルからジャンルキーを判定"""
    title_lower = title_text.lower()
    if '予約' in title_lower:
        return '予約'
    elif any(kw in title_lower for kw in ['期間限定', 'sale', 'セール']):
        return '限定'
    elif '新色' in title_lower:
        return '新色'
    elif '再入荷' in title_lower:
        return '再入荷'
    elif '入荷' in title_lower:
        return '入荷'
    return 'その他'


def get_genre_config_by_title(title_text):
    """ジャンルキーから配色設定を取得"""
    genre_key = classify_genre(title_text)
    for g in GENRE_CONFIG:
        if g['key'] == genre_key:
            return g
    return DEFAULT_GENRE


def fetch_real_genre_items():
    """サイトから5ジャンルそれぞれの実商品・実URL・実画像を自動抽出"""
    found_items = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # 1. トップページ取得
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        soup = BeautifulSoup(page.content(), 'html.parser')
        
        for a_tag in soup.find_all('a', href=True):
            text = a_tag.get_text(strip=True)
            if len(text) <= 3:
                continue
            
            genre_key = classify_genre(text)
            if genre_key != 'その他' and genre_key not in found_items:
                item_url = clean_url(TARGET_URL, a_tag['href'])
                cleaned_title = clean_title(text)
                found_items[genre_key] = {
                    'genre_key': genre_key,
                    'title': cleaned_title,
                    'raw_title': text,
                    'url': item_url
                }
            
            if len(found_items) >= 5:
                break
                
        # 2. 各商品の詳細ページから本物の画像を抽出
        items_list = list(found_items.values())
        for item in items_list:
            img_url = DEFAULT_IMAGE_URL
            try:
                page.goto(item['url'], wait_until="domcontentloaded", timeout=20000)
                detail_soup = BeautifulSoup(page.content(), 'html.parser')
                
                for img in detail_soup.find_all('img', src=True):
                    src = img['src']
                    if any(ex in src.lower() for ex in ['blank.gif', 'spacer.gif', 'logo', 'banner', 'btn', 'cart', 'header', 'footer']):
                        continue
                    
                    full_img = urljoin(item['url'], src)
                    if full_img.startswith("http://"):
                        full_img = full_img.replace("http://", "https://", 1)
                    
                    img_url = full_img
                    if any(kw in src.lower() for kw in ['upload', 'save_image', 'goods', 'product']):
                        break
            except Exception as e:
                print(f"詳細ページの画像解析エラー ({item['url']}): {e}")

            item['image_url'] = img_url

        browser.close()
    return items_list


def create_flex_carousel(items):
    """5ジャンル別の色分けカルーセルを作成"""
    bubbles = []
    for item in items:
        genre = get_genre_config_by_title(item['raw_title'])

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
        "altText": f"【リアルデータ5色テスト】新着更新（{len(items)}件）",
        "contents": {
            "type": "carousel",
            "contents": bubbles
        }
    }


def main():
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("エラー: LINEのアクセス情報が設定されていません。")
        return

    print("サイトから各ジャンルのリアルな掲載商品と画像を自動取得中...")
    items = fetch_real_genre_items()

    if not items:
        print("有効な商品情報が取得できませんでした。")
        return

    print(f"\n--- 抽出成功データ ({len(items)}件) ---")
    for item in items:
        print(f"[{item['genre_key']}] {item['title']}")
        print(f"  URL: {item['url']}")
        print(f"  IMG: {item['image_url']}")
    print("------------------------------------\n")

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
        print("LINEへリアルデータ＆実画像での5色テスト通知を送信しました。")
    else:
        print(f"LINE送信エラー: {res.status_code} - {res.text}")


if __name__ == "__main__":
    main()
