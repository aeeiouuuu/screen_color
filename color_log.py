"""色の変化ログ (CSV) の書き込み・読み込み

ログは 1 行 1 イベントで、PC ごと・日ごとに別ファイルになります。
    logs/<PC名>_<YYYYMMDD>.csv
列: timestamp, pc, event, color
    event = START (監視開始) / COLOR (色が変わった) / END (監視終了)
"""
import csv
import glob
import os
import socket
from datetime import datetime

FIELDS = ["timestamp", "pc", "event", "color"]
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def resolve_pc_name(cfg):
    return cfg.get("pc_name") or socket.gethostname()


def resolve_log_dir(cfg, base_dir):
    d = cfg.get("log_dir") or "logs"
    return d if os.path.isabs(d) else os.path.join(base_dir, d)


class ColorLogger:
    def __init__(self, log_dir, pc_name):
        self.log_dir = log_dir
        self.pc = pc_name
        os.makedirs(log_dir, exist_ok=True)

    def write(self, event, color="", when=None):
        when = when or datetime.now()
        path = os.path.join(self.log_dir, f"{self.pc}_{when:%Y%m%d}.csv")
        new_file = not os.path.exists(path)
        # utf-8-sig: Excel で開いても文字化けしない
        with open(path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(FIELDS)
            w.writerow([when.strftime(TIME_FMT), self.pc, event, color])


def read_logs(log_dir):
    """フォルダ内の全ログを読み込み、時刻順のレコードのリストを返す"""
    records = []
    for path in sorted(glob.glob(os.path.join(log_dir, "*.csv"))):
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    row["timestamp"] = datetime.strptime(row["timestamp"], TIME_FMT)
                except (KeyError, ValueError):
                    continue
                records.append(row)
    records.sort(key=lambda r: (r["pc"], r["timestamp"]))
    return records


def build_segments(records):
    """レコードを「ある色が続いた区間」のリストに変換する

    区間の終わり = 同じ PC の次のレコードの時刻。
    次のレコードが START (前回が異常終了) の場合や、最後の区間は終わりが不明なので捨てる。
    """
    segments = []
    by_pc = {}
    for r in records:
        by_pc.setdefault(r["pc"], []).append(r)

    for pc, rows in by_pc.items():
        for cur, nxt in zip(rows, rows[1:]):
            if cur["event"] != "COLOR" or nxt["event"] == "START":
                continue
            start, end = cur["timestamp"], nxt["timestamp"]
            segments.append({
                "pc": pc,
                "color": cur["color"],
                "start": start,
                "end": end,
                "seconds": (end - start).total_seconds(),
            })
    return segments
