"""
ダミーデータ送信スクリプト（継続実行版）

すくすくステップAPIにダミーデータを5秒ごとに送信し続けます。
歩数と距離は同時に送信し、歩数は累積していきます。
"""

import sys
import datetime
import random
import time


# 各児童の累積歩数を追跡
child_step_counters = {}


def init_step_counters(child_ids: list) -> None:
    """
    各児童の歩数カウンターを初期化（0から開始）

    Args:
        child_ids: 児童IDのリスト
    """
    for child_id in child_ids:
        # 0歩から開始
        child_step_counters[child_id] = 0


def get_steps_increment(cycle_count: int) -> int:
    """
    サイクル数に応じた歩数の増加量を生成

    サイクル数が増えるほど多くの歩数を追加する（線形増加）

    Args:
        cycle_count: 現在のサイクル数

    Returns:
        増加量（100 + cycle_count * 50 歩）
    """
    return 100 + cycle_count * 50


def generate_realistic_distance() -> float:
    """
    現実的な距離（0.5-50.0km）を生成する

    Returns:
        距離（km、float）
    """
    return round(random.uniform(0.5, 50.0), 2)


def send_step_and_distance_data(
    child_id: int, 
    date: datetime.datetime,
    cycle_count: int,
    base_url: str = "http://localhost:8000"
) -> bool:
    """
    歩数データと距離データを同時に送信する

    Args:
        child_id: 児童ID
        date: 日期
        cycle_count: 現在のサイクル数
        base_url: サーバのベースURL

    Returns:
        送信成功時はTrue
    """
    import requests
    
    url = f"{base_url}/api/push_data"
    
    # 累積歩数を更新
    if child_id not in child_step_counters:
        child_step_counters[child_id] = 0
    child_step_counters[child_id] += get_steps_increment(cycle_count)
    current_steps = child_step_counters[child_id]
    
    # 距離データを生成（ランダムな相手児童との距離）
    payload = {
        "child_id": child_id,
        "singledata": {
            "date": date.isoformat(),
            "steps": current_steps
        },
        "distances": [
            {
                "date": date.isoformat(),
                "with_child": (child_id % 10) + 1,  # ランダムな相手（1-10）
                "distance": generate_realistic_distance()
            }
        ]
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        return result.get("status") == "ok"
    except requests.exceptions.RequestException as e:
        print(f"  ❌ データ送信に失敗: {e}")
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
    
    # 歩数カウンターを初期化
    init_step_counters(existing_child_ids)
    print("📊 初期歩数: 全児童 0歩\n")
    
    print("🔄 5秒ごとにデータを送信し続けます...")
    print("   - 歩数: 累積（1回あたり 100 + サイクル数×50 歩増加）")
    print("   - 距離: ランダムなペアで送信")
    print("   終了するには Ctrl+C を押してください。\n")
    
    # ループカウンター
    cycle_count = 0
    
    try:
        while True:
            cycle_count += 1
            current_time = datetime.datetime.now()
            
            # 各児童に交互にデータを送信
            for child_id in existing_child_ids:
                success = send_step_and_distance_data(child_id, current_time, cycle_count, base_url)
                
                if success:
                    steps = child_step_counters.get(child_id, 0)
                    increment = get_steps_increment(cycle_count)
                    print(f"[{current_time.strftime('%H:%M:%S')}] 児童 {child_id}: 歩数 {steps:,} 歩 (+{increment})")
                else:
                    print(f"[{current_time.strftime('%H:%M:%S')}] 児童 {child_id}: 送信失敗")
            
            # 次のサイクルまでの待機
            print(f"--- サイクル {cycle_count} 完了 ---")
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print(f"\n\n⏹️ 送信を停止しました（合計 {cycle_count} サイクル）")
        print(f"📊 最終歩数: {dict((k, f'{v:,}') for k, v in child_step_counters.items())}")
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