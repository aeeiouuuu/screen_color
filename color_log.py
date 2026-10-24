"""色の変化ログ (CSV) の書き込み・読み込み

ログは 1 行 1 イベントで、PC ごと・日ごとに別ファイルになります。
    logs/<PC名>_<YYYYMMDD>.csv
列: timestamp, pc, event, color
    event = START (監視開始) / COLOR (色が変わった) / END (監視終了)
            HIDE (対象が見えなくなった。color 列に理由) / SHOW (また見えるようになった)
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
    """レコードを「ある色が続いた区間」に変換する

    戻り値: (segments, hides)
      segments: {pc, session, color, start, end, seconds, hidden}
                hidden = 区間のうち対象が見えていなかった秒数
      hides:    {pc, start, end}  見えていなかった期間

    - 区間の終わり = 次の COLOR / END の時刻 (HIDE/SHOW では区切らない)
    - START が来たら前回は異常終了とみなし、終わりの分からない区間は捨てる
    """
    segments, hides = [], []
    by_pc = {}
    for r in records:
        by_pc.setdefault(r["pc"], []).append(r)

    for pc, rows in by_pc.items():
        cur = None
        hide_start = None
        session = 0

        def close_hide(t):
            nonlocal hide_start
            if hide_start is None:
                return
            hides.append({"pc": pc, "start": hide_start, "end": t})
            if cur:
                cur["hidden"] += (t - hide_start).total_seconds()
            hide_start = None

        for r in rows:
            t, ev = r["timestamp"], r["event"]
            if ev == "START":
                cur, hide_start = None, None
                session += 1
            elif ev == "HIDE":
                if hide_start is None:
                    hide_start = t
            elif ev == "SHOW":
                close_hide(t)
            elif ev in ("COLOR", "END"):
                close_hide(t)
                if cur:
                    cur["end"] = t
                    cur["seconds"] = (t - cur["start"]).total_seconds()
                    segments.append(cur)
                cur = None
                if ev == "COLOR":
                    cur = {"pc": pc, "session": session, "color": r["color"].lower(),
                           "start": t, "hidden": 0.0}
    return segments, hides
