import os
import requests

# --- 設定項目 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# テスト用のダミーデータ（1件のみ）
TEST_ITEM = [{
    'item_id': 'test_001',
    'title': '【テスト通知】越谷トラウトアイランドBot 動作確認用サンプル商品',
    'url': 'https://www.area-island.com/',
    'image_url': 'https://via.placeholder.com/300x200.png?text=TEST+ITEM'
}]


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
        "altText": "【テスト通知】越谷トラウトアイランドBot動作テスト",
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
        "messages": [create_flex_carousel(TEST_ITEM)]
    }

    res = requests.post(url, headers=headers, json=payload, timeout=10)
    if res.status_code == 200:
        print("テスト通知（1件）の送信に成功しました。LINEをご確認ください。")
    else:
        print(f"LINE送信エラー: {res.status_code} - {res.text}")


if __name__ == "__main__":
    main()
