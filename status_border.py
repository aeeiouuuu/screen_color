"""状態表示ボーダー
config.json の座標の色を 0.5 秒ごとに読み取り、画面の外周を同じ色の枠で塗ります。
色が変わるたびに logs/ フォルダへ記録します (analyze.py で分析)。
枠は常に最前面・クリックは下の画面に素通りするので作業の邪魔になりません。

誤検知の対策:
- window_title を設定すると、読み取り位置に対象ウィンドウが見えているか確認する
  (他のウィンドウが重なっていたら「見えていない」扱い。色の変化として数えない)
- labels を設定すると、その色に近い色だけを状態として受け付ける
- 同じ色が stable_samples 回続いたときだけ「変わった」とみなす (ちらつき対策)
- 見えていない間、枠は最後の色のまま。同じ色で戻ったら続きとして扱う

終了: このプログラムを起動したコンソールで Ctrl+C、またはコンソールを閉じる。
"""
import ctypes
import os
import signal
import tkinter as tk

from color_log import ColorLogger, resolve_log_dir, resolve_pc_name
from screen_utils import (CONFIG_PATH, get_pixel, load_config,
                          nearest_label_color, screen_size, set_dpi_aware,
                          to_hex, window_title_at)

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x2

user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.restype = ctypes.c_long

HIDDEN = "hidden"  # 「見えていない」状態を表す内部の値


def make_click_through(win):
    """ウィンドウをクリック透過・タスクバー非表示にする"""
    win.update_idletasks()
    hwnd = user32.GetParent(win.winfo_id())
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)


def main():
    set_dpi_aware()
    cfg = load_config()
    x, y = int(cfg["x"]), int(cfg["y"])
    b = int(cfg["border"])
    interval_ms = int(float(cfg["interval_sec"]) * 1000)
    stable_needed = max(1, int(cfg["stable_samples"]))
    title = cfg.get("window_title") or ""
    labels = {k.lower(): v for k, v in (cfg.get("labels") or {}).items()}
    tolerance = float(cfg["color_tolerance"])
    w, h = screen_size()
    logger = ColorLogger(resolve_log_dir(cfg, os.path.dirname(CONFIG_PATH)),
                         resolve_pc_name(cfg))

    if x < b or y < b or x >= w - b or y >= h - b:
        print(f"警告: 読み取り座標 ({x}, {y}) が枠 (太さ {b}px) に隠れます。"
              "枠の色を読んでしまうので、座標か border を見直してください。")
    if not title:
        print("注意: window_title が未設定のため、他のウィンドウが重なっても検知できません。")
    if not labels:
        print("注意: labels が未設定のため、読み取った色をすべて状態として扱います。")

    root = tk.Tk()
    root.withdraw()

    # 上・下・左・右の4本の帯 (中央は覆わない)
    rects = [
        (0, 0, w, b),
        (0, h - b, w, b),
        (0, b, b, h - 2 * b),
        (w - b, b, b, h - 2 * b),
    ]
    bars = []
    for (bx, by, bw, bh) in rects:
        bar = tk.Toplevel(root)
        bar.overrideredirect(True)
        bar.attributes("-topmost", True)
        bar.geometry(f"{bw}x{bh}+{bx}+{by}")
        bar.config(bg="gray")
        make_click_through(bar)
        bars.append(bar)

    state = {
        "candidate": None,  # 直近に読めた値
        "streak": 0,        # candidate が何回続いたか
        "reason": "",
        "current": None,    # 確定した値 (色コード or HIDDEN)
        "color": None,      # 最後に確定した色 (見えていない間も保持)
        "count": 0,
    }

    def read():
        """今の状態を (値, 理由) で返す。値は色コード or HIDDEN"""
        if title and title not in window_title_at(x, y):
            return HIDDEN, "covered"
        rgb = get_pixel(x, y)
        if rgb is None:
            return HIDDEN, "unreadable"
        if labels:
            code = nearest_label_color(rgb, labels, tolerance)
            return (code, "") if code else (HIDDEN, f"unknown {to_hex(rgb)}")
        return to_hex(rgb), ""

    def confirm(value, reason):
        prev = state["current"]
        state["current"] = value
        if value == HIDDEN:
            logger.write("HIDE", reason)
            print(f"見えなくなりました ({reason})")
            return
        if prev == HIDDEN:
            logger.write("SHOW")
            print("見えるようになりました")
        if value != state["color"]:
            for bar in bars:
                bar.config(bg=value)
            print(f"色が変わりました: {value} {labels.get(value, '')}")
            logger.write("COLOR", value)
            state["color"] = value

    def tick():
        value, reason = read()
        if value == state["candidate"]:
            state["streak"] += 1
        else:
            state["candidate"], state["streak"], state["reason"] = value, 1, reason
        if state["streak"] >= stable_needed and value != state["current"]:
            confirm(value, state["reason"])

        # 他のウィンドウに最前面を取られても戻す (約5秒ごと)
        state["count"] += 1
        if state["count"] % 10 == 0:
            for bar in bars:
                bar.attributes("-topmost", True)
                bar.lift()

        root.after(interval_ms, tick)

    print(f"監視開始: 座標 ({x}, {y}), 間隔 {interval_ms}ms, 枠 {b}px  (終了は Ctrl+C)")
    print(f"ログ保存先: {logger.log_dir}  (PC名: {logger.pc})")
    logger.write("START")
    signal.signal(signal.SIGINT, lambda *_: root.destroy())
    tick()
    try:
        root.mainloop()
    finally:
        logger.write("END")


if __name__ == "__main__":
    main()
