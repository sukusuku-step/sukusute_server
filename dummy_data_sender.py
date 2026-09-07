"""
ダミーデータ送信スクリプト（20デバイスシミュレーション版）

すくすくステップAPIに20デバイスのデータをシミュレート送信します。
各デバイスには固有のID、送信間隔、位置情報、バッテリー状態などが設定されています。
"""

import sys
import datetime
import random
import time
import uuid


# ===== 20デバイスの設定 =====
# 各デバイスに固有のID、名前、送信間隔、位置情報、データタイプを設定

DEVICE_CONFIGS = [
    {"device_id": 1,  "name": "デバイス-001", "interval": 5,  "data_type": "both",    "base_lat": 35.6812, "base_lon": 139.7671, "zone": "東京・丸の内"},
    {"device_id": 2,  "name": "デバイス-002", "interval": 7,  "data_type": "steps",   "base_lat": 35.6850, "base_lon": 139.7700, "zone": "東京・竹橋"},
    {"device_id": 3,  "name": "デバイス-003", "interval": 10, "data_type": "distance","base_lat": 35.6890, "base_lon": 139.6917, "zone": "東京・新宿"},
    {"device_id": 4,  "name": "デバイス-004", "interval": 4,  "data_type": "both",    "base_lat": 35.6580, "base_lon": 139.7414, "zone": "東京・渋谷"},
    {"device_id": 5,  "name": "デバイス-005", "interval": 12, "data_type": "steps",   "base_lat": 35.6762, "base_lon": 139.6503, "zone": "東京・池袋"},
    {"device_id": 6,  "name": "デバイス-006", "interval": 6,  "data_type": "distance","base_lat": 35.7100, "base_lon": 139.8107, "zone": "東京・上野"},
    {"device_id": 7,  "name": "デバイス-007", "interval": 8,  "data_type": "both",    "base_lat": 35.6640, "base_lon": 139.7350, "zone": "東京・新橋"},
    {"device_id": 8,  "name": "デバイス-008", "interval": 15, "data_type": "steps",   "base_lat": 35.6930, "base_lon": 139.7036, "zone": "東京・四ツ谷"},
    {"device_id": 9,  "name": "デバイス-009", "interval": 5,  "data_type": "distance","base_lat": 35.6720, "base_lon": 139.7650, "zone": "東京・銀座"},
    {"device_id": 10, "name": "デバイス-010", "interval": 9,  "data_type": "both",    "base_lat": 35.6860, "base_lon": 139.6940, "zone": "東京・中野"},
    {"device_id": 11, "name": "デバイス-011", "interval": 11, "data_type": "steps",   "base_lat": 35.6780, "base_lon": 139.7340, "zone": "東京・恵比寿"},
    {"device_id": 12, "name": "デバイス-012", "interval": 6,  "data_type": "distance","base_lat": 35.6980, "base_lon": 139.7730, "zone": "東京・秋葉原"},
    {"device_id": 13, "name": "デバイス-013", "interval": 13, "data_type": "both",    "base_lat": 35.6690, "base_lon": 139.7080, "zone": "東京・代々木"},
    {"device_id": 14, "name": "デバイス-014", "interval": 7,  "data_type": "steps",   "base_lat": 35.6830, "base_lon": 139.7550, "zone": "東京・神田"},
    {"device_id": 15, "name": "デバイス-015", "interval": 10, "data_type": "distance","base_lat": 35.6750, "base_lon": 139.7250, "zone": "東京・飯田橋"},
    {"device_id": 16, "name": "デバイス-016", "interval": 4,  "data_type": "both",    "base_lat": 35.6910, "base_lon": 139.7800, "zone": "東京・日本橋"},
    {"device_id": 17, "name": "デバイス-017", "interval": 14, "data_type": "steps",   "base_lat": 35.6670, "base_lon": 139.7400, "zone": "東京・品川"},
    {"device_id": 18, "name": "デバイス-018", "interval": 8,  "data_type": "distance","base_lat": 35.6840, "base_lon": 139.7620, "zone": "東京・有楽町"},
    {"device_id": 19, "name": "デバイス-019", "interval": 5,  "data_type": "both",    "base_lat": 35.6950, "base_lon": 139.6980, "zone": "東京・立川"},
    {"device_id": 20, "name": "デバイス-020", "interval": 11, "data_type": "steps",   "base_lat": 35.6730, "base_lon": 139.7180, "zone": "東京・調布"},
]


# 児童の名前リスト（20人分）
CHILD_NAMES = [
    "太郎", "花子", "直樹", "洋子", "明",
    "さくら", "大輔", "美咲", "拓海", "結衣",
    "健太", "愛", "翔太", "光", "怜",
    "葵", "悠真", "彩花", "颯太", "瑞希"
]


# ===== 各デバイスの状態管理 =====
class DeviceState:
    """デバイスの状態を管理するクラス"""
    
    def __init__(self, config: dict):
        self.device_id: int = config["device_id"]
        self.name: str = config["name"]
        self.interval: int = config["interval"]
        self.data_type: str = config["data_type"]
        self.base_lat: float = config["base_lat"]
        self.base_lon: float = config["base_lon"]
        self.zone: str = config["zone"]
        self.child_id: int = config["device_id"]  # device_idとchild_idを連動
        self.steps: int = 0  # 累積歩数
        self.battery: int = random.randint(60, 100)  # バッテリー残量
        self.last_lat: float = config["base_lat"]
        self.last_lon: float = config["base_lon"]
        self.send_count: int = 0  # 送信回数
    
    def get_device_info(self) -> dict:
        """デバイスの情報を返す"""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "child_id": self.child_id,
            "zone": self.zone,
            "battery": self.battery,
            "interval": self.interval,
            "data_type": self.data_type,
            "send_count": self.send_count,
        }


def init_devices() -> list[DeviceState]:
    """
    20デバイスを初期化
    
    Returns:
        初期化されたデバイスリスト
    """
    devices = []
    for config in DEVICE_CONFIGS:
        device = DeviceState(config)
        devices.append(device)
    return devices


def generate_realistic_position(device: DeviceState) -> tuple[float, float]:
    """
    現実的な位置情報を生成（少しランダムに移動）
    
    Args:
        device: デバイス状態
        
    Returns:
        (latitude, longitude)
    """
    # 1回の移動で約10-100m移動すると仮定
    lat_offset = random.uniform(-0.0005, 0.0005)  # 約50m
    lon_offset = random.uniform(-0.0005, 0.0005)  # 約50m
    
    device.last_lat += lat_offset
    device.last_lon += lon_offset
    
    return device.last_lat, device.last_lon


def generate_realistic_steps(device: DeviceState, cycle_count: int) -> int:
    """
    現実的な歩数の増加量を生成
    
    Args:
        device: デバイス状態
        cycle_count: サイクル数
        
    Returns:
        増加した歩数
    """
    # 1回あたり10-50歩、サイクルが経つほど少し増加
    base_increment = random.randint(10, 50)
    cycle_bonus = cycle_count // 10  # 10サイクルごとに1歩追加
    return max(1, base_increment + cycle_bonus)


def generate_realistic_distance(child_id_1: int, child_id_2: int, device1: DeviceState, device2: DeviceState) -> dict:
    """
    2児童間の現実的な距離を生成（2-60mの範囲）
    
    距離データは双方向に送信される（A->BとB->A）
    複数の子ども間の距離もシミュレート
    
    Args:
        child_id_1: 児童1のID
        child_id_2: 児童2のID
        device1: 児童1のデバイス状態
        device2: 児童2のデバイス状態
        
    Returns:
        距離データ（distanceを含む）
    """
    # 2-60mの範囲（0.002km - 0.060km）
    # 近い距離をより確率高く（正規分布に近い形状）
    distance_m = random.gauss(30, 15)  # 平均30m、標準偏差15m
    distance_m = max(2, min(60, distance_m))  # 2-60mにクリップ
    distance_km = round(distance_m / 1000.0, 4)
    
    return {
        "distance": distance_km,
        "distance_m": distance_m,
    }


def send_device_data(
    device: DeviceState,
    date: datetime.datetime,
    cycle_count: int,
    devices: list[DeviceState],
    base_url: str = "http://localhost:8000"
) -> bool:
    """
    デバイスデータをAPIに送信
    
    バックエンドが受け付ける形式:
    {
        "child_id": int,
        "singledata": {"date": str, "steps": int},  # optional
        "distances": [{"date": str, "with_child": int, "distance": float}]  # optional
    }
    
    追加フィールド（battery, latitude, longitudeなど）はサーバー側で無視される。
    
    Args:
        device: 送信デバイス
        date: 日期
        cycle_count: サイクル数
        devices: 全デバイスリスト（距離計算用）
        base_url: サーバのベースURL
        
    Returns:
        送信成功時はTrue
    """
    import requests
    
    url = f"{base_url}/api/push_data"
    
    # 現在時刻
    timestamp = datetime.datetime.now()
    iso_date = timestamp.isoformat()
    
    # 位置情報を生成（デバイス側の状態として保持）
    lat, lon = generate_realistic_position(device)
    
    # バッテリーを徐々に消費（1送信ごとに0-1%）
    device.battery = max(5, device.battery - random.randint(0, 1))
    
    # バックエンドのChildDataRecord形式に準拠したペイロード
    payload: dict = {
        "child_id": device.child_id,
    }
    
    # データタイプに応じてデータを送信
    if device.data_type in ("steps", "both"):
        # 歩数データを追加（バックエンド形式: {date, steps}）
        increment = generate_realistic_steps(device, cycle_count)
        device.steps += increment
        payload["singledata"] = {
            "date": iso_date,
            "steps": device.steps,
        }
    
    if device.data_type in ("distance", "both"):
        # 距離データを追加（バックエンド形式: [{date, with_child, distance}]）
        # 複数デバイスとの距離データを一度に送信
        # 20m-60mの範囲の距離を2-4個の他デバイスとの距離として送信
        
        # ランダムに2-4人の他デバイスを選択
        other_devices = random.sample(
            [d for d in devices if d.device_id != device.device_id],
            min(random.randint(2, 4), len(devices) - 1)
        )
        
        distances_list = []
        for other_device in other_devices:
            dist_data = generate_realistic_distance(device.child_id, other_device.child_id, device, other_device)
            distances_list.append({
                "date": iso_date,
                "with_child": other_device.child_id,
                "distance": dist_data["distance"],
            })
        
        payload["distances"] = distances_list
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()
        
        if result.get("status") == "ok":
            device.send_count += 1
            return True
        return False
    except requests.exceptions.RequestException as e:
        print(f"    ⚠ 送信失敗: {e}")
        return False


def create_debug_children(base_url: str = "http://localhost:8000", count: int = 20) -> list[int]:
    """
    デバッグ用児童を複数作成
    
    Args:
        base_url: サーバのベースURL
        count: 作成する児童数
        
    Returns:
        作成された児童IDリスト
    """
    import requests
    
    for i in range(count):
        url = f"{base_url}/api/create_debug_child"
        try:
            response = requests.post(url)
            response.raise_for_status()
            # サーバーが準備するのを待つ
            time.sleep(0.5)
        except requests.exceptions.RequestException as e:
            print(f"  ⚠ 児童 {i+1} 作成失敗: {e}")
            return []
    
    # 作成後に児童一覧を取得
    time.sleep(1)  # すべてコミットされるのを待つ
    list_url = f"{base_url}/api/children"
    try:
        list_response = requests.get(list_url)
        if list_response.ok:
            children_data = list_response.json()
            if children_data.get("status") == "ok":
                return [c["child_id"] for c in children_data.get("children", [])]
    except requests.exceptions.RequestException as e:
        print(f"  ⚠ 児童一覧取得失敗: {e}")
    
    return []


def sync_child_ids(devices: list[DeviceState], base_url: str = "http://localhost:8000") -> bool:
    """
    デバイスIDとサーバー上の児童IDを同期
    
    Args:
        devices: デバイスリスト
        base_url: サーバのベースURL
        
    Returns:
        同期成功時はTrue
    """
    import requests
    
    max_retries = 5
    for retry in range(max_retries):
        try:
            list_url = f"{base_url}/api/children"
            response = requests.get(list_url, timeout=5)
            
            if not response.ok:
                time.sleep(1)
                continue
            
            data = response.json()
            children = data.get("children", [])
            
            # 児童数がデバイス数より少ない場合は作成
            if len(children) < len(devices):
                missing = len(devices) - len(children)
                print(f"📋 児童数が不足しています。{missing}人作成します...")
                created_ids = create_debug_children(base_url, missing)
                if not created_ids:
                    time.sleep(1)
                    continue
                # 再度取得
                time.sleep(1)
                response = requests.get(list_url, timeout=5)
                if response.ok:
                    children = response.json().get("children", [])
                else:
                    continue
            
            if len(children) >= len(devices):
                # 児童IDをデバイスに割り当て
                for i, device in enumerate(devices):
                    device.child_id = children[i]["child_id"]
                
                print(f"✅ {len(children)}人の児童IDをデバイスに割り当てました")
                return True
            
        except requests.exceptions.RequestException as e:
            if retry < max_retries - 1:
                print(f"  ⚠ 接続再試行中... ({retry+1}/{max_retries})")
                time.sleep(2)
            else:
                print(f"❌ 児童IDの同期に失敗: {e}")
                return False
    
    print("❌ 児童IDの同期に失敗しました。最大再試行回数を超えました。")
    return False


def run_device_simulation(
    devices: list[DeviceState],
    base_url: str = "http://localhost:8000",
    master_interval: int = 5
) -> None:
    """
    20デバイスのシミュレーションを実行
    
    各デバイスが独自のインターバルでデータを送信し続けます。
    
    Args:
        devices: デバイスリスト
        base_url: サーバのベースURL
        master_interval: メインループの間隔（秒）
    """
    import requests
    
    print("=" * 80)
    print("すくすくステップ ダミーデータ送信スクリプト（20デバイスシミュレーション版）")
    print("=" * 80)
    print()
    
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
    
    print("✅ サーバに接続しました")
    print()
    
    # 児童IDを同期
    if not sync_child_ids(devices, base_url):
        print("❌ 児童IDの同期に失敗しました。終了します。")
        sys.exit(1)
    
    print()
    print("=" * 80)
    print("デバイス一覧")
    print("=" * 80)
    print(f"{'ID':>4} | {'名前':>10} | {'間隔':>4} | {'データ型':>8} | {'ゾーン':>10} | {'バッテリー':>7}")
    print("-" * 80)
    for device in devices:
        info = device.get_device_info()
        print(f"{info['device_id']:>4} | {info['name']:>10} | {info['interval']:>4}秒 | {info['data_type']:>8} | {info['zone']:>10} | {info['battery']:>5}%")
    print("=" * 80)
    print()
    
    # 送信間隔の設定
    # 各デバイスのインターバルの最小公倍数に近い値でループ
    # 各デバイスが自分のインターバルで送信できるようにする
    print("🔄 デバイスシミュレーションを開始します...")
    print("   - 各デバイスが独自のインターバルでデータを送信")
    print("   - 歩数データ: 累積値（徐々に増加）")
    print("   - 距離データ: 2-60mの範囲で複数デバイス間の双方向距離")
    print("   終了するには Ctrl+C を押してください。\n")
    
    # サイクルカウンター
    cycle_count = 0
    # 各デバイスの次回送信時刻（秒）
    next_send_times = {d.device_id: 0 for d in devices}
    
    try:
        while True:
            cycle_count += 1
            current_time = datetime.datetime.now()
            elapsed = cycle_count * master_interval
            
            print(f"[{current_time.strftime('%H:%M:%S')}] --- サイクル {cycle_count} ---")
            
            # 各デバイスの送信判定
            for device in devices:
                if elapsed >= next_send_times[device.device_id]:
                    # このデバイスが送信
                    success = send_device_data(device, current_time, cycle_count, devices, base_url)
                    
                    if success:
                        info = device.get_device_info()
                        print(f"  ✅ {info['name']} (ID:{device.child_id}): "
                              f"歩数 {device.steps:,} 歩 | "
                              f"バッテリー {device.battery}% | "
                              f"位置 ({device.last_lat:.4f}, {device.last_lon:.4f})")
                    else:
                        print(f"  ❌ {device.name}: 送信失敗")
                    
                    # 次回の送信時刻を計算
                    next_send_times[device.device_id] = elapsed + device.interval
            
            # 次のサイクルまで待機
            time.sleep(master_interval)
            
    except KeyboardInterrupt:
        print(f"\n\n⏹️ シミュレーションを停止しました（合計 {cycle_count} サイクル）")
        print()
        print("=" * 80)
        print("📊 最終統計")
        print("=" * 80)
        print(f"{'ID':>4} | {'名前':>10} | {'ゾーン':>10} | {'総歩数':>8} | {'送信回':>6} | {'バッテリー':>7}")
        print("-" * 80)
        for device in sorted(devices, key=lambda d: d.device_id):
            info = device.get_device_info()
            print(f"{info['device_id']:>4} | {info['name']:>10} | {info['zone']:>10} | {device.steps:>8,} | {info['send_count']:>6} | {info['battery']:>5}%")
        print("=" * 80)


def main() -> None:
    """メイン関数"""
    # デバイスを初期化
    devices = init_devices()
    
    # コマンドライン引数でマスター間隔を指定可能
    master_interval = 5
    if len(sys.argv) > 1:
        try:
            master_interval = int(sys.argv[1])
        except ValueError:
            print(f"間隔（秒）を指定してください。デフォルト: {master_interval}")
    
    # シミュレーション実行
    run_device_simulation(devices, master_interval=master_interval)


if __name__ == "__main__":
    main()