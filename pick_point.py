"""座標確認ツール
マウスを色を読みたい場所に合わせて F8 を押すと、その座標を config.json に保存します。
Esc か ウィンドウの × で終了。
"""
import ctypes
import tkinter as tk

from screen_utils import (get_cursor_pos, get_pixel, load_config, save_config,
                          set_dpi_aware, to_hex)

VK_F8 = 0x77
VK_ESCAPE = 0x1B
GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState


def main():
    set_dpi_aware()
    cfg = load_config()

    root = tk.Tk()
    root.title("座標確認ツール")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    info = tk.Label(root, font=("Meiryo", 14), justify="left", width=24, anchor="w")
    info.pack(padx=10, pady=(10, 4))
    swatch = tk.Label(root, width=30, height=3, relief="solid", bd=1)
    swatch.pack(padx=10, pady=4)
    saved = tk.Label(root, font=("Meiryo", 11), fg="#006600",
                     text=f"現在の設定: ({cfg['x']}, {cfg['y']})")
    saved.pack(padx=10, pady=4)
    tk.Label(root, font=("Meiryo", 10),
             text="マウスを合わせて F8 で保存 / Esc で終了").pack(padx=10, pady=(4, 10))

    state = {"f8": False}

    def tick():
        x, y = get_cursor_pos()
        rgb = get_pixel(x, y)
        if rgb:
            info.config(text=f"X: {x}  Y: {y}\nRGB: {rgb}  {to_hex(rgb)}")
            swatch.config(bg=to_hex(rgb))

        f8_down = bool(GetAsyncKeyState(VK_F8) & 0x8000)
        if f8_down and not state["f8"]:  # 押した瞬間だけ反応
            cfg["x"], cfg["y"] = x, y
            save_config(cfg)
            saved.config(text=f"保存しました: ({x}, {y})")
        state["f8"] = f8_down

        if GetAsyncKeyState(VK_ESCAPE) & 0x8000:
            root.destroy()
            return
        root.after(50, tick)

    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
