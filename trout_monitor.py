import os
import requests

# --- 設定項目 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# 実際の掲載データを元にした5ジャンルテストデータ
TEST_ITEMS = [
    {
        'title': '【ご予約】 ロデオクラフト フォーナインマイスター・イエローウルフ【62L】 TI限定カラー',
        'raw_title': '【ご予約】 ロデオクラフト フォーナインマイスター・イエローウルフ【62L】 TI限定カラー',
        'url': 'https://www.area-island.com/?pid=192780573',
        'image_url': 'https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop'
    },
    {
        'title': '期間限定 Summer sale 【ベルベットアーツ】夏の応援企画',
        'raw_title': '期間限定 Summer sale 【ベルベットアーツ】夏の応援企画',
        'url': 'https://www.area-island.com/',
        'image_url': 'https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop'
    },
    {
        'title': '8/20 アンデットファクトリー レム23SSSR 新色入荷',
        'raw_title': '8/20 アンデットファクトリー レム23SSSR 新色入荷',
        'url': 'https://www.area-island.com/',
        'image_url': 'https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop'
    },
    {
        'title': '8/21 ラッキークラフト FCTワウ33SDS 再入荷',
        'raw_title': '8/21 ラッキークラフト FCTワウ33SDS 再入荷',
        'url': 'https://www.area-island.com/',
        'image_url': 'https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop'
    },
    {
        'title': '8/21 「越トラ」オリジナル!! ディスプラウト ピコピコイーグルプレーヤーMS 【カフェコーク】 入荷',
        'raw_title': '8/21 「越トラ」オリジナル!! ディスプラウト ピコピコイーグルプレーヤーMS 【カフェコーク】 入荷',
        'url': 'https://www.area-island.com/',
        'image_url': 'https://images.unsplash.com/photo-1544551763-46a013bb70d5?w=600&auto=format&fit=crop'
    }
]

# ジャンルデザイン設定
GENRE_CONFIG = [
    {'keywords': ['予約'], 'category': '【ご予約】', 'color': '#FF5722'},                # オレンジ
    {'keywords': ['期間限定', 'sale', 'セール'], 'category': '【期間限定】', 'color': '#8E24AA'}, # パープル
    {'keywords': ['新色'], 'category': '【新色入荷】', 'color': '#EC407A'},              # ピンク
    {'keywords': ['再入荷'], 'category': '【再入荷】', 'color': '#1E88E5'},              # ブルー
    {'keywords': ['入荷'], 'category': '【新着入荷】', 'color': '#1DB446'},              # グリーン
]
DEFAULT_GENRE = {'category': '【新着更新】', 'color': '#607D8B'}


def get_genre_config(title):
    """ジャンル判別"""
    title_lower = title.lower()
    for genre in GENRE_CONFIG:
        if any(kw.lower() in title_lower for kw in genre['keywords']):
            return genre
    return DEFAULT_GENRE


def create_flex_carousel(items):
    """5ジャンル分のカードを作成"""
    bubbles = []
    for item in items:
        genre = get_genre_config(item['raw_title'])

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
        "altText": "【デザインテスト】5ジャンル別カラー表示テスト",
        "contents": {
            "type": "carousel",
            "contents": bubbles
        }
    }


def main():
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("エラー: LINEのアクセス情報が設定されていません。")
        return

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    payload = {
        "to": LINE_USER_ID,
        "messages": [create_flex_carousel(TEST_ITEMS)]
    }

    res = requests.post(url, headers=headers, json=payload, timeout=10)
    if res.status_code == 200:
        print("5ジャンルの色分けテスト通知をLINEに送信しました。")
    else:
        print(f"LINE送信エラー: {res.status_code} - {res.text}")


if __name__ == "__main__":
    main()
