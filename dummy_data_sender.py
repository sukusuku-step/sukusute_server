"""
ダミーデータ送信スクリプト（継続実行版）

すくすくステップAPIにダミーデータを5秒ごとに送信し続けます。
"""

import sys
import datetime
import random
import time


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


def get_last_7_days() -> list:
    """
    過去7日間の日期を生成する

    Returns:
        日期のリスト（最新日が先頭）
    """
    today = datetime.datetime.now()
    return [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]


def send_step_data(child_id: int, date: datetime.datetime, steps: int, base_url: str = "http://localhost:8000") -> bool:
    """
    歩数データを送信する

    Args:
        child_id: 児童ID
        date: 日期
        steps: 歩数
        base_url: サーバのベースURL

    Returns:
        送信成功時はTrue
    """
    import requests
    
    url = f"{base_url}/api/push_data"
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


def send_distance_data(child_id: int, date: datetime.datetime, with_child: int, distance: float, base_url: str = "http://localhost:8000") -> bool:
    """
    距離データを送信する

    Args:
        child_id: 児童ID
        date: 日期
        with_child: 相手児童ID
        distance: 距離（km）
        base_url: サーバのベースURL

    Returns:
        送信成功時はTrue
    """
    import requests
    
    url = f"{base_url}/api/push_data"
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


def create_debug_child(base_url: str = "http://localhost:8000") -> int:
    """
    デバッグ用児童を作成する

    Args:
        base_url: サーバのベースURL

    Returns:
        作成された児童のID（失敗時は0）
    """
    import requests
    
    url = f"{base_url}/api/create_debug_child"
    try:
        response = requests.post(url)
        response.raise_for_status()
        print("✏️ 児童を作成しました")
        return get_max_child_id(base_url)
    except requests.exceptions.RequestException as e:
        print(f"❌ 児童の作成に失敗しました: {e}")
        return 0


def get_max_child_id(base_url: str = "http://localhost:8000") -> int:
    """
    既存の最大の児童IDを取得する

    Args:
        base_url: サーバのベースURL

    Returns:
        最大の児童ID（存在しない場合は0）
    """
    import requests
    
    for i in range(20, 0, -1):
        try:
            url = f"{base_url}/api/children/{i}"
            response = requests.get(url)
            if response.ok:
                return i
        except requests.exceptions.RequestException:
            continue
    return 0


def send_all_dummy_data(base_url: str = "http://localhost:8000", interval: int = 5) -> None:
    """
    各児童に交互にダミーデータを送信し続ける

    Args:
        base_url: サーバのベースURL
        interval: 送信間隔（秒）
    """
    import requests
    
    print("=" * 60)
    print("すくすくステップ ダミーデータ送信スクリプト（継続実行版）")
    print(f"送信間隔: {interval}秒")
    print("=" * 60)
    
    # サーバのヘルスチェック
    try:
        response = requests.get(f"{base_url}/api/health")
        if response.json().get("status") != "ok":
            print("❌ サーバが応答しません。サーバを起動してください。")
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"❌ サーバへの接続に失敗しました: {e}")
        print(f"   サーバが実行中か確認してください: {base_url}")
        sys.exit(1)
    
    print("✅ サーバに接続しました\n")
    
    # 既存の児童IDを取得
    existing_child_ids = []
    for i in range(1, 21):
        try:
            response = requests.get(f"{base_url}/api/children/{i}")
            if response.ok:
                existing_child_ids.append(i)
        except requests.exceptions.RequestException:
            pass
    
    print(f"📋 既存の児童: {existing_child_ids}\n")
    
    if not existing_child_ids:
        print("📋 児童がいません。新しい児童を作成します...")
        new_id = create_debug_child(base_url)
        if new_id > 0:
            existing_child_ids.append(new_id)
        else:
            print("❌ 児童の作成に失敗しました。終了します。")
            sys.exit(1)
    
    print(f"📋 対象児童ID: {existing_child_ids}\n")
    print("🔄 5秒ごとにデータを送信し続けます...")
    print("   終了するには Ctrl+C を押してください。\n")
    
    # 過去7日間の日期を事前に生成
    days = get_last_7_days()
    
    # ループカウンター
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            current_time = datetime.datetime.now()
            
            # 各児童に交互にデータを送信
            for idx, child_id in enumerate(existing_child_ids):
                # 各サイクルで異なるデータタイプを送信
                if cycle_count % 2 == 1:
                    # 奇数サイクル: 歩数データ
                    day = days[random.randint(0, len(days) - 1)]
                    steps = generate_realistic_steps()
                    step_time = datetime.datetime(day.year, day.month, day.day, 18, 0, 0)
                    
                    if send_step_data(child_id, step_time, steps, base_url):
                        print(f"[{current_time.strftime('%H:%M:%S')}] 児童 {child_id}: 歩数 {steps} 歩 を送信")
                else:
                    # 偶数サイクル: 距離データ
                    day = days[random.randint(0, len(days) - 1)]
                    for other_id in existing_child_ids:
                        if other_id != child_id:
                            distance = generate_realistic_distance()
                            distance_time = datetime.datetime(day.year, day.month, day.day, 12, 0, 0)
                            if send_distance_data(child_id, distance_time, other_id, distance, base_url):
                                print(f"[{current_time.strftime('%H:%M:%S')}] 児童 {child_id} -> {other_id}: 距離 {distance} km を送信")
                            break  # 1人の相手とのみ送信
                
                # 各送信の間に短い待機（サーバーに負荷をかけないため）
                time.sleep(0.1)
            
            # 次のサイクルまでの待機
            print(f"--- サイクル {cycle_count} 完了 ---")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\n\n⏹️ 送信を停止しました（合計 {cycle_count} サイクル）")
        print("=" * 60)


def main() -> None:
    """メイン関数"""
    # コマンドライン引数で間隔を指定可能
    interval = 5
    if len(sys.argv) > 1:
        try:
            interval = int(sys.argv[1])
        except ValueError:
            print(f"間隔（秒）を指定してください。デフォルト: {interval}")
    
    send_all_dummy_data(interval=interval)


if __name__ == "__main__":
    main()