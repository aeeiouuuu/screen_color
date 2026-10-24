"""座標確認ツール
マウスを色を読みたい場所に合わせて F8 を押すと、その座標とウィンドウのタイトルを
config.json に保存します。
F9 を押すと、マウス位置の色を labels に追加します (名前はあとで config.json で編集)。
Esc か ウィンドウの × で終了。
"""
import ctypes
import tkinter as tk

from screen_utils import (get_cursor_pos, get_pixel, load_config, save_config,
                          set_dpi_aware, to_hex, window_title_at)

VK_F8 = 0x77
VK_F9 = 0x78
VK_ESCAPE = 0x1B
GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
TOOL_TITLE = "座標確認ツール"


def main():
    set_dpi_aware()
    cfg = load_config()

    root = tk.Tk()
    root.title(TOOL_TITLE)
    root.attributes("-topmost", True)
    root.resizable(False, False)

    info = tk.Label(root, font=("Meiryo", 13), justify="left", width=34, anchor="w")
    info.pack(padx=10, pady=(10, 4))
    swatch = tk.Label(root, width=40, height=3, relief="solid", bd=1)
    swatch.pack(padx=10, pady=4)
    saved = tk.Label(root, font=("Meiryo", 10), fg="#006600", justify="left", anchor="w",
                     width=46, wraplength=420,
                     text=f"現在の設定: ({cfg['x']}, {cfg['y']})  {cfg.get('window_title') or '(ウィンドウ名なし)'}")
    saved.pack(padx=10, pady=4)
    tk.Label(root, font=("Meiryo", 10), justify="left",
             text="F8: 座標とウィンドウ名を保存\nF9: この色を labels に追加\nEsc: 終了"
             ).pack(padx=10, pady=(4, 10))

    keys = {VK_F8: False, VK_F9: False}

    def pressed(vk):
        """押した瞬間だけ True"""
        down = bool(GetAsyncKeyState(vk) & 0x8000)
        hit = down and not keys[vk]
        keys[vk] = down
        return hit

    def tick():
        x, y = get_cursor_pos()
        rgb = get_pixel(x, y)
        title = window_title_at(x, y)
        if rgb:
            info.config(text=f"X: {x}  Y: {y}\nRGB: {rgb}  {to_hex(rgb)}\nウィンドウ: {title or '-'}")
            swatch.config(bg=to_hex(rgb))

        if pressed(VK_F8):
            if title == TOOL_TITLE:
                saved.config(text="このツールの上では保存できません。対象の位置にマウスを移してください。")
            else:
                cfg["x"], cfg["y"] = x, y
                cfg["window_title"] = title
                save_config(cfg)
                saved.config(text=f"保存しました: ({x}, {y})  ウィンドウ名「{title}」")
        if pressed(VK_F9) and rgb:
            code = to_hex(rgb)
            labels = dict(cfg.get("labels") or {})
            labels.setdefault(code, f"色{len(labels) + 1}")
            cfg["labels"] = labels
            save_config(cfg)
            saved.config(text=f"labels に追加しました: {code} 「{labels[code]}」"
                              "（名前は config.json で変更してください）")

        if GetAsyncKeyState(VK_ESCAPE) & 0x8000:
            root.destroy()
            return
        root.after(50, tick)

    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
