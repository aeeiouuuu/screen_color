"""デモ用のサンプルログを作る (10台 × 数日分)

  python make_sample_logs.py            # sample_logs/ に 10台 × 5日分
  python make_sample_logs.py --days 10

作ったログは analyze.py --log-dir sample_logs で分析できます。
色はデモ用コンフィグプログラム (demo_config_app.py) と同じです。
"""
import argparse
import os
import random
import shutil
from datetime import datetime, timedelta

from color_log import ColorLogger
from demo_config_app import STATES

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# PC ごとのクセ (エラー率, 作業時間の倍率, 対応の遅さの倍率)
# — 分析で差が見えるようにわざと偏らせる
PC_PROFILE = {f"LINE-PC{i:02d}": (0.06, 1.0, 1.0) for i in range(1, 11)}
PC_PROFILE["LINE-PC03"] = (0.05, 1.35, 1.0)  # 作業が遅い PC
PC_PROFILE["LINE-PC07"] = (0.25, 1.0, 1.0)   # エラーが多い PC
PC_PROFILE["LINE-PC10"] = (0.06, 1.0, 2.5)   # 見回りから遠く、対応が遅れがちな PC
HIDE_RATE = 0.03  # 区間の途中で他のウィンドウが重なる確率

# 各状態の長さ (秒)
DURATION = {"待機": (30, 240), "進行中": (420, 600), "エラー": (60, 400), "完了": (20, 120)}


def simulate_day(logger, day, error_rate, slow, resp):
    shifts = [(day.replace(hour=8, minute=30), day.replace(hour=12)),
              (day.replace(hour=13), day.replace(hour=17, minute=30))]
    for start, end in shifts:
        t = start + timedelta(seconds=random.randint(0, 300))
        logger.write("START", when=t)
        state = "待機"
        while t < end:
            logger.write("COLOR", STATES[state], when=t)
            lo, hi = DURATION[state]
            sec = random.uniform(lo, hi)
            if state == "進行中":
                sec *= slow
            if state in ("エラー", "完了"):
                sec *= resp
            if random.random() < HIDE_RATE:  # 途中で他のウィンドウが重なる
                h0 = t + timedelta(seconds=random.uniform(0, sec * 0.7))
                logger.write("HIDE", "covered", when=h0)
                h1 = min(h0 + timedelta(seconds=random.uniform(5, 90)),
                         t + timedelta(seconds=sec - 1))
                logger.write("SHOW", when=h1)
            # 夕方は少しエラーが増える
            rate = error_rate * (1.6 if t.hour >= 15 else 1.0)
            t += timedelta(seconds=sec)
            if state == "待機":
                state = "進行中"
            elif state == "進行中":
                state = "エラー" if random.random() < rate else "完了"
            elif state == "エラー":
                state = "進行中"
            else:
                state = "待機"
        logger.write("END", when=min(t, end + timedelta(minutes=10)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--out", default=os.path.join(BASE_DIR, "sample_logs"))
    args = ap.parse_args()

    random.seed(1)
    if os.path.isdir(args.out):
        shutil.rmtree(args.out)

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days = []
    d = today - timedelta(days=1)
    while len(days) < args.days:  # 土日を除いた直近の平日
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)

    for pc, (err, slow, resp) in PC_PROFILE.items():
        logger = ColorLogger(args.out, pc)
        for day in sorted(days):
            simulate_day(logger, day, err, slow, resp)

    print(f"サンプルログを作成しました: {args.out}  ({len(PC_PROFILE)}台 × {len(days)}日)")


if __name__ == "__main__":
    main()
