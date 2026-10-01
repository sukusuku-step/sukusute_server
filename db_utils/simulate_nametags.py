"""Simulate M5 nametags by sending the same CSV and status formats as the firmware."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import math
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import requests


MAX_SIMULATED_DEVICES = 30
FAMILY_NAMES = [
    "Sato", "Suzuki", "Takahashi", "Tanaka", "Ito", "Watanabe", "Yamamoto", "Nakamura", "Kobayashi", "Kato",
    "Yoshida", "Yamada", "Sasaki", "Yamaguchi", "Matsumoto", "Inoue", "Kimura", "Hayashi", "Shimizu", "Saito",
]
GIVEN_NAMES = [
    "Hina", "Ren", "Rin", "Ao", "Yui", "Minato", "Sakura", "Yuma", "Aoi", "Haruto",
    "Misaki", "Itsuki", "Mei", "Yamato", "Riko", "Asahi", "Tsumugi", "Sota", "An", "Ritsu",
]
SIM_NAME_PATTERN = re.compile(r"^Sim(\d+)-")
CSV_HEADER = [
    "Timestamp", "Steps", "Ax", "Ay", "Az", "Gx", "Gy", "Gz", "Mx", "My", "Mz", "Start",
]


@dataclass
class SimulatedNametag:
    slot: int
    name: str
    child_id: int
    rng: random.Random
    started_at: dt.datetime = field(default_factory=dt.datetime.now)
    x: float = 0.0
    y: float = 0.0
    steps: int = 30
    samples_sent: int = 0
    battery: int = 0
    peers: list[SimulatedNametag] = field(default_factory=list)
    low_activity: bool = False


def request_json(method: str, url: str, **kwargs) -> dict:
    response = requests.request(method, url, timeout=10, **kwargs)
    response.raise_for_status()
    return response.json()


def random_simulator_name(slot: int, used_names: set[str], rng: random.Random) -> str:
    while True:
        name = f"Sim{slot - 1:02d}-{rng.choice(FAMILY_NAMES)}{rng.choice(GIVEN_NAMES)}"
        if name not in used_names:
            used_names.add(name)
            return name


def enroll_devices(base_url: str, count: int, rng: random.Random) -> list[tuple[str, int]]:
    children_response = request_json("GET", f"{base_url}/api/children")
    children = children_response.get("children", [])
    used_names = {child["name"] for child in children}
    existing: dict[int, tuple[str, int]] = {}
    for child in children:
        match = SIM_NAME_PATTERN.match(child["name"])
        if match:
            slot = int(match.group(1)) + 1
            if 1 <= slot <= count:
                existing.setdefault(slot, (child["name"], child["child_id"]))

    devices = []
    for slot in range(1, count + 1):
        if slot in existing:
            devices.append(existing[slot])
            continue
        name = random_simulator_name(slot, used_names, rng)
        response = request_json(
            "GET", f"{base_url}/api/children/search", params={"name": name}
        )
        devices.append((response["name"], response["child_id"]))
    return devices


def calculate_distance_from_rssi(rssi: int) -> float:
    tx_power = -59
    ratio = rssi / tx_power
    if ratio < 1.0:
        return ratio**10
    return 0.89976 * ratio**7.7095 + 0.111


def distance_to_rssi(distance_m: float) -> int:
    distance_m = max(0.05, min(50.0, distance_m))
    if distance_m < 1.0:
        return round(-59 * distance_m**0.1)
    ratio = ((distance_m - 0.111) / 0.89976) ** (1 / 7.7095)
    return round(-59 * ratio)


def create_devices(
    enrolled: list[tuple[str, int]],
    rng: random.Random,
    initial_samples: int = 100,
    low_activity_count: int = 0,
) -> list[SimulatedNametag]:
    started_at = dt.datetime.now() - dt.timedelta(seconds=(initial_samples - 1) / 10.0)
    devices = [
        SimulatedNametag(
            slot=slot,
            name=name,
            child_id=child_id,
            rng=random.Random(rng.randrange(2**32)),
            started_at=started_at,
            x=rng.uniform(0, 10),
            y=rng.uniform(0, 10),
            battery=rng.randint(65, 100),
            low_activity=slot <= low_activity_count,
        )
        for slot, (name, child_id) in enumerate(enrolled, start=1)
    ]
    for device in devices:
        device.peers = sorted(
            (other for other in devices if other is not device),
            key=lambda other: math.hypot(device.x - other.x, device.y - other.y),
        )[: min(5, len(devices) - 1)]
    return devices


def make_csv_batch(
    device: SimulatedNametag, samples: int, advance_steps: bool = True
) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(CSV_HEADER + [f"Distance_{peer.child_id}" for peer in device.peers])
    start_text = device.started_at.strftime("%Y-%m-%d %H:%M:%S")

    for row_index in range(samples):
        sample_index = device.samples_sent + row_index
        phase = sample_index * math.tau / 7.0
        low_activity_now = device.low_activity and advance_steps
        if advance_steps and not device.low_activity and device.rng.random() < 0.14:
            device.steps += 1

        motion_scale = 0.08 if low_activity_now else 1.0
        noise_scale = 0.01 if low_activity_now else 0.025
        gyro_scale = 0.2 if low_activity_now else 2.0
        ax = 0.08 * motion_scale * math.sin(phase) + device.rng.gauss(0, noise_scale)
        ay = 0.06 * motion_scale * math.cos(phase) + device.rng.gauss(0, noise_scale)
        az = 1.0 + 0.18 * motion_scale * math.sin(phase) + device.rng.gauss(0, noise_scale)
        gx = 8.0 * motion_scale * math.cos(phase) + device.rng.gauss(0, gyro_scale)
        gy = 5.0 * motion_scale * math.sin(phase) + device.rng.gauss(0, gyro_scale)
        gz = device.rng.gauss(0, gyro_scale)
        mx = 25.0 + device.rng.gauss(0, 1.5)
        my = 5.0 + device.rng.gauss(0, 1.5)
        mz = 40.0 + device.rng.gauss(0, 1.5)

        distances = []
        for peer in device.peers:
            physical_distance = math.hypot(device.x - peer.x, device.y - peer.y)
            noisy_distance = max(0.1, physical_distance + device.rng.gauss(0, 0.15))
            rssi = distance_to_rssi(noisy_distance)
            distances.append(f"{calculate_distance_from_rssi(rssi):.2f}")

        writer.writerow([
            f"{sample_index / 10.0:.1f}", device.steps,
            f"{ax:.4f}", f"{ay:.4f}", f"{az:.4f}",
            f"{gx:.4f}", f"{gy:.4f}", f"{gz:.4f}",
            f"{mx:.4f}", f"{my:.4f}", f"{mz:.4f}",
            start_text if row_index == 0 else "",
            *distances,
        ])

    device.samples_sent += samples
    return output.getvalue()


def send_device_batch(
    base_url: str,
    device: SimulatedNametag,
    samples: int,
    advance_steps: bool = True,
) -> None:
    if device.rng.random() < 0.01:
        device.battery = max(5, device.battery - 1)

    request_json(
        "POST",
        f"{base_url}/api/device_status",
        json={
            "child_id": device.child_id,
            "battery": device.battery,
            "wifi_rssi": device.rng.randint(-75, -40),
        },
    )
    response = requests.post(
        f"{base_url}/api/push_csv/{device.child_id}",
        data=make_csv_batch(device, samples, advance_steps).encode("utf-8"),
        headers={"Content-Type": "text/csv"},
        timeout=300,
    )
    response.raise_for_status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M5 nametag 1〜30台シミュレーター")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="APIのベースURL（M5実機の各APIパスを付加。既定: localhost:8000）",
    )
    parser.add_argument(
        "--count", type=int, default=MAX_SIMULATED_DEVICES,
        help=f"シミュレーション台数（1〜{MAX_SIMULATED_DEVICES}、既定: {MAX_SIMULATED_DEVICES}）",
    )
    parser.add_argument(
        "--low-activity-count", type=int, default=3,
        help="低活動として歩数とセンサー変動を抑える台数（既定: 3）",
    )
    parser.add_argument("--interval", type=float, default=10.0, help="送信周期（秒）")
    parser.add_argument("--samples", type=int, default=100, help="1回あたりのCSVサンプル数（実機は100）")
    parser.add_argument("--warmup-samples", type=int, default=6000, help="初回にまとめて送る10Hzサンプル数（推論には6000以上必要）")
    parser.add_argument("--workers", type=int, default=6, help="同時送信スレッド数")
    parser.add_argument("--cycles", type=int, default=0, help="送信回数。0ならCtrl+Cまで継続")
    parser.add_argument("--seed", type=int, help="乱数シード（名前・センサー値を再現）")
    args = parser.parse_args()
    if not 1 <= args.count <= MAX_SIMULATED_DEVICES:
        parser.error(f"countは1〜{MAX_SIMULATED_DEVICES}の範囲で指定してください")
    if not 0 <= args.low_activity_count <= args.count:
        parser.error("low-activity-countは0以上count以下で指定してください")
    if args.interval <= 0 or args.samples < 1 or args.warmup_samples < 6000 or args.workers < 1 or args.cycles < 0:
        parser.error("samples/workersは1以上、warmup-samplesは6000以上、intervalは0より大きく、cyclesは0以上にしてください")
    return args


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    rng = random.Random(args.seed)

    try:
        health = request_json("GET", f"{base_url}/api/health")
        if health.get("status") != "ok":
            raise RuntimeError("server health check did not return status=ok")
        enrolled = enroll_devices(base_url, args.count, rng)
    except (requests.RequestException, RuntimeError, KeyError) as error:
        print(f"サーバー接続または児童登録に失敗しました: {error}", file=sys.stderr)
        return 1

    devices = create_devices(
        enrolled, rng, args.warmup_samples, args.low_activity_count
    )
    print(f"{base_url} に接続しました。{len(devices)}台の名札をシミュレーションします。")
    print("CSV: 実機と同じ10Hzサンプル、加速度/ジャイロ/地磁気9軸、BLE距離列")
    print("端末状態: battery と wifi_rssi を送信。Ctrl+Cで停止します。")
    for device in devices:
        activity_label = " [低活動]" if device.low_activity else ""
        print(f"  {device.child_id:>3}: {device.name}{activity_label}")

    total_pairs = len(devices) * (len(devices) - 1) // 2
    print(f"初回ウォームアップ: 全{total_pairs}ペア分の距離データを{args.warmup_samples}件ずつ順番に送信します...")
    for device in devices:
        nearby_peers = device.peers
        device.peers = [other for other in devices if other.child_id > device.child_id]
        device.started_at = dt.datetime.now() - dt.timedelta(
            seconds=(args.warmup_samples - 1) / 10.0
        )
        try:
            send_device_batch(
                base_url, device, args.warmup_samples, advance_steps=False
            )
        except requests.RequestException as error:
            print(f"初回ウォームアップの送信に失敗しました: {device.name}: {error}", file=sys.stderr)
            return 1
        finally:
            device.peers = nearby_peers
    print("関係推論用の初期データを送信しました。通常送信を開始します。")

    cycle = 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            while args.cycles == 0 or cycle < args.cycles:
                cycle += 1
                cycle_started = time.monotonic()
                futures = {
                    executor.submit(
                        send_device_batch,
                        base_url,
                        device,
                        args.samples,
                        not device.low_activity,
                    ): device
                    for device in devices
                }
                successes = 0
                for future in as_completed(futures):
                    device = futures[future]
                    try:
                        future.result()
                        successes += 1
                    except requests.RequestException as error:
                        print(f"送信失敗 child_id={device.child_id} name={device.name}: {error}")
                print(f"cycle {cycle}: {successes}/{len(devices)}台送信成功")
                if args.cycles == 0 or cycle < args.cycles:
                    time.sleep(max(0.0, args.interval - (time.monotonic() - cycle_started)))
    except KeyboardInterrupt:
        print("\nシミュレーションを停止しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())