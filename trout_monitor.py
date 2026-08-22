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

# 万が一画像が取得できない場合のフォールバック画像
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


def fetch_real_single_item():
    """トップページからリンクを取得し、個別商品ページへジャンプして実際の画像を抽出"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # 1. トップページへアクセス
        page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        soup = BeautifulSoup(page.content(), 'html.parser')
        keywords = ['入荷', '再入荷', '新色', 'ご予約', '限定']

        target_item = None
        for a_tag in soup.find_all('a', href=True):
            text = a_tag.get_text(strip=True)
            if any(kw in text for kw in keywords) and len(text) > 3:
                item_url = clean_url(TARGET_URL, a_tag['href'])
                cleaned_title = clean_title(text)
                target_item = {'title': cleaned_title, 'url': item_url}
                break

        if not target_item:
            browser.close()
            return None

        # 2. 個別商品ページへ移動してメイン画像を抽出
        img_url = DEFAULT_IMAGE_URL
        try:
            page.goto(target_item['url'], wait_until="domcontentloaded", timeout=30000)
            detail_soup = BeautifulSoup(page.content(), 'html.parser')
            
            # 商品ページ内の画像からメイン写真を特定
            for img in detail_soup.find_all('img', src=True):
                src = img['src']
                # バナー・ロゴ・ボタンなどの非商品画像を除外
                if any(ex in src.lower() for ex in ['blank.gif', 'spacer.gif', 'logo', 'banner', 'btn', 'cart', 'header', 'footer']):
                    continue
                
                full_img = urljoin(target_item['url'], src)
                # LINE仕様に合わせてHTTPをHTTPSに補正
                if full_img.startswith("http://"):
                    full_img = full_img.replace("http://", "https://", 1)
                
                img_url = full_img
                # アップロード画像や商品画像と思われるパスを最優先採用
                if any(kw in src.lower() for kw in ['upload', 'save_image', 'goods', 'product']):
                    break
        except Exception as e:
            print(f"詳細ページの画像解析中にエラーが発生しました: {e}")

        browser.close()
        target_item['image_url'] = img_url
        return target_item


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
        "altText": f"【実画像テスト】{item['title']}",
        "contents": {
            "type": "carousel",
            "contents": [bubble]
        }
    }


def main():
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("エラー: LINEのアクセストークンまたはユーザーIDが設定されていません。")
        return

    print("サイトから最新データおよび商品画像の取得を開始します...")
    item = fetch_real_single_item()

    if not item:
        print("エラー: 有効な商品情報が抽出できませんでした。")
        return

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
        print("LINEへ最新の商品画像付き通知（1件）を送信しました。")
    else:
        print(f"LINE送信エラー: {res.status_code} - {res.text}")


if __name__ == "__main__":
    main()
