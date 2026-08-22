import os
import re
import hashlib
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 設定項目 ---
TARGET_URL = "https://www.area-island.com/"
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# 画像が存在しない場合の予備画像（HTTPS対応）
DEFAULT_IMAGE_URL = "https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop"


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


def clean_image_url(base_url, img_element):
    """画像URLの抽出と検証"""
    if not img_element:
        return DEFAULT_IMAGE_URL
    src = (
        img_element.get('data-src') or 
        img_element.get('data-original') or 
        img_element.get('src')
    )
    if not src or 'blank.gif' in src or 'spacer.gif' in src:
        return DEFAULT_IMAGE_URL
    
    full_img_url = urljoin(base_url, src)
    # HTTPの場合はLINE側で拒否されるためHTTPSへ補正
    if full_img_url.startswith("http://"):
        full_img_url = full_img_url.replace("http://", "https://", 1)
    return full_img_url


def fetch_real_single_item():
    """実際のWebサイトから最新の1件のみを抽出"""
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

            # 検出された最初の1件を返す
            return {
                'title': cleaned_title,
                'url': item_url,
                'image_url': img_url
            }
    return None


def create_flex_carousel(item):
    """LINE Flex Message用データ構造を作成"""
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

    return {
        "type": "flex",
        "altText": f"【実データテスト】{item['title']}",
        "contents": {
            "type": "carousel",
            "contents": [bubble]
        }
    }


def main():
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("エラー: LINEのアクセストークンまたはユーザーIDが設定されていません。")
        return

    print("サイトから最新データの取得を開始します...")
    item = fetch_real_single_item()

    if not item:
        print("エラー: サイトから有効な入荷情報を抽出できませんでした。")
        return

    # 抽出されたデータの確認ログ出力
    print("\n--- 抽出成功データ ---")
    print(f"タイトル: {item['title']}")
    print(f"商品URL : {item['url']}")
    print(f"画像URL : {item['image_url']}")
    print("----------------------\n")

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    payload = {
        "to": LINE_USER_ID,
        "messages": [create_flex_carousel(item)]
    }

    res = requests.post(url, headers=headers, json=payload, timeout=10)
    if res.status_code == 200:
        print("LINEへ実データ（1件）の送信に成功しました。スマホのLINEをご確認ください。")
    else:
        print(f"LINE送信エラー: {res.status_code} - {res.text}")


if __name__ == "__main__":
    main()
