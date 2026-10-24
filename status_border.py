"""状態表示ボーダー
config.json の座標の色を 0.5 秒ごとに読み取り、画面の外周を同じ色の枠で塗ります。
色が変わるたびに logs/ フォルダへ記録します (analyze.py で分析)。
枠は常に最前面・クリックは下の画面に素通りするので作業の邪魔になりません。
終了: このプログラムを起動したコンソールで Ctrl+C、またはコンソールを閉じる。
"""
import ctypes
import os
import signal
import tkinter as tk

from color_log import ColorLogger, resolve_log_dir, resolve_pc_name
from screen_utils import (CONFIG_PATH, get_pixel, load_config, screen_size,
                          set_dpi_aware, to_hex)

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x2

user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.restype = ctypes.c_long


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
    w, h = screen_size()
    logger = ColorLogger(resolve_log_dir(cfg, os.path.dirname(CONFIG_PATH)),
                         resolve_pc_name(cfg))

    if x < b or y < b or x >= w - b or y >= h - b:
        print(f"警告: 読み取り座標 ({x}, {y}) が枠 (太さ {b}px) に隠れます。"
              "枠の色を読んでしまうので、座標か border を見直してください。")

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

    state = {"color": None, "count": 0}

    def tick():
        rgb = get_pixel(x, y)
        if rgb is not None:
            color = to_hex(rgb)
            if color != state["color"]:
                for bar in bars:
                    bar.config(bg=color)
                print(f"色が変わりました: {rgb} {color}")
                logger.write("COLOR", color)
                state["color"] = color

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
