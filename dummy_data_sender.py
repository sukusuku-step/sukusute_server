"""
ダミーデータ送信スクリプト

すくすくステップAPIにダミーデータを送信するスクリプトです。
最後の7日間の歩数データと距離データを生成して送信します。
"""

import sys
import datetime
import random
import requests

# サーバのベースURL
BASE_URL = "http://localhost:8000"


def create_debug_child() -> int:
    """
    デバッグ用児童を作成する

    Returns:
        作成された児童のID（失敗時は0）
    """
    url = f"{BASE_URL}/api/create_debug_child"
    try:
        response = requests.post(url)
        response.raise_for_status()
        print("✏️ 児童を作成しました")
        # 作成された児童のIDを取得するために、全児童を取得
        return get_max_child_id()
    except requests.exceptions.RequestException as e:
        print(f"❌ 児童の作成に失敗しました: {e}")
        return 0


def get_max_child_id() -> int:
    """
    既存の最大の児童IDを取得する

    Returns:
        最大の児童ID（存在しない場合は0）
    """
    for i in range(20, 0, -1):
        try:
            url = f"{BASE_URL}/api/children/{i}"
            response = requests.get(url)
            if response.ok:
                return i
        except requests.exceptions.RequestException:
            continue
    return 0


def generate_realistic_steps() -> int:
    """
    現実的な歩数（1000-15000歩）を生成する

    Returns:
        歩数（int）
    """
    return random.randint(1000, 15000)


def generate_realistic_distance() -> float:
    """
    現実的な距離（0.5-50.0km）を生成する

    Returns:
        距離（km、float）
    """
    return round(random.uniform(0.5, 50.0), 2)


def get_last_7_days() -> list[datetime.datetime]:
    """
    過去7日間の日期を生成する

    Returns:
        日期のリスト（最新日が先頭）
    """
    today = datetime.datetime.now()
    return [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]


def send_step_data(child_id: int, date: datetime.datetime, steps: int) -> bool:
    """
    歩数データを送信する

    Args:
        child_id: 児童ID
        date: 日期
        steps: 歩数

    Returns:
        送信成功時はTrue
    """
    url = f"{BASE_URL}/api/push_data"
    payload = {
        "child_id": child_id,
        "singledata": {
            "date": date.isoformat(),
            "steps": steps
        }
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        return result.get("status") == "ok"
    except requests.exceptions.RequestException as e:
        print(f"  ❌ 歩数データの送信に失敗: {e}")
        return False


def send_distance_data(child_id: int, date: datetime.datetime, with_child: int, distance: float) -> bool:
    """
    距離データを送信する

    Args:
        child_id: 児童ID
        date: 日期
        with_child: 相手児童ID
        distance: 距離（km）

    Returns:
        送信成功時はTrue
    """
    url = f"{BASE_URL}/api/push_data"
    payload = {
        "child_id": child_id,
        "distances": [
            {
                "date": date.isoformat(),
                "with_child": with_child,
                "distance": distance
            }
        ]
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        return result.get("status") == "ok"
    except requests.exceptions.RequestException as e:
        print(f"  ❌ 距離データの送信に失敗: {e}")
        return False


def send_dummy_data_for_child(child_id: int, existing_child_ids: list[int]) -> None:
    """
    特定の児童に対してダミーデータを送信する

    Args:
        child_id: 児童ID
        existing_child_ids: 既存の児童IDリスト（距離データ用）
    """
    print(f"\n📊 児童 {child_id} のダミーデータを送信中...")
    
    days = get_last_7_days()
    
    for day in days:
        # 歩数データ
        steps = generate_realistic_steps()
        step_time = datetime.datetime(day.year, day.month, day.day, 18, 0, 0)
        if send_step_data(child_id, step_time, steps):
            print(f"  ✅ {day.strftime('%Y-%m-%d')} の歩数: {steps} 歩")
        
        # 距離データ（既存の児童との距離）
        for other_id in existing_child_ids:
            if other_id != child_id:
                distance = generate_realistic_distance()
                distance_time = datetime.datetime(day.year, day.month, day.day, 12, 0, 0)
                send_distance_data(child_id, distance_time, other_id, distance)


def main() -> None:
    """
    メイン関数
    """
    print("=" * 50)
    print("すくすくステップ ダミーデータ送信スクリプト")
    print("=" * 50)
    
    # サーバのヘルスチェック
    try:
        response = requests.get(f"{BASE_URL}/api/health")
        if response.json().get("status") != "ok":
            print("❌ サーバが応答しません。サーバを起動してください。")
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ サーバへの接続に失敗しました: {e}")
        print(f"   サーバが実行中か確認してください: {BASE_URL}")
        sys.exit(1)
    
    print("✅ サーバに接続しました\n")
    
    # 既存の児童IDを取得
    existing_child_ids = []
    for i in range(1, 21):
        try:
            response = requests.get(f"{BASE_URL}/api/children/{i}")
            if response.ok:
                existing_child_ids.append(i)
        except requests.exceptions.RequestException:
            pass
    
    print(f"📋 既存の児童: {existing_child_ids}\n")
    
    # 新しい児童を3人作成
    new_child_ids = []
    for _ in range(3):
        new_id = create_debug_child()
        if new_id > 0:
            new_child_ids.append(new_id)
    
    # 全児童IDを統合
    all_child_ids = list(set(existing_child_ids + new_child_ids))
    all_child_ids.sort()
    
    print(f"\n📋 全体の児童ID: {all_child_ids}\n")
    
    # 各児童にダミーデータを送信
    for child_id in all_child_ids:
        other_ids = [i for i in all_child_ids if i != child_id]
        send_dummy_data_for_child(child_id, other_ids)
    
    print("\n" + "=" * 50)
    print("✅ ダミーデータの送信が完了しました")
    print("=" * 50)


if __name__ == "__main__":
    main()