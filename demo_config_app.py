"""デモ用の仮コンフィグプログラム

本物のコンフィグプログラムの代わりに、状態を色で表示する小さなウィンドウを出します。
status_border.py の動作確認・デモ用です。

  python demo_config_app.py

- 「自動モード」: 待機 → 進行中 → (たまにエラー) → 完了 を自動で繰り返す
- ボタンで手動で状態を切り替えることもできる
- 「この位置を config に設定」: 状態表示の座標・ウィンドウ名・色の名前を config.json に書き込む
"""
import random
import tkinter as tk

from screen_utils import load_config, save_config, set_dpi_aware

# 状態ごとの色 (本物のプログラムの色とは無関係なデモ用)
STATES = {
    "待機":   "#808080",
    "進行中": "#0078d7",
    "エラー": "#ffc000",
    "完了":   "#00b050",
}
DEMO_LABELS = {color: name for name, color in STATES.items()}
DEMO_ROLES = {"done": "完了", "error": "エラー"}
WINDOW_TITLE = "Config Tool (DEMO)"

# 自動モードの各状態の長さ (秒)
DURATION = {"待機": (3, 6), "進行中": (8, 15), "エラー": (4, 8), "完了": (2, 4)}
ERROR_RATE = 0.2

WINDOW_POS = (300, 200)  # ウィンドウの位置は固定 (本物と同じ想定)


class DemoApp:
    def __init__(self, root):
        self.root = root
        root.title(WINDOW_TITLE)
        root.geometry(f"+{WINDOW_POS[0]}+{WINDOW_POS[1]}")
        root.resizable(False, False)

        top = tk.Frame(root, padx=10, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="Status:", font=("Meiryo", 11)).pack(side="left")
        self.lamp = tk.Frame(top, width=40, height=40, relief="solid", bd=1)
        self.lamp.pack(side="left", padx=8)
        self.state_label = tk.Label(top, font=("Meiryo", 14, "bold"), width=8, anchor="w")
        self.state_label.pack(side="left")

        self.progress = tk.Canvas(root, width=320, height=16, bg="white",
                                  highlightthickness=1, highlightbackground="#999")
        self.progress.pack(padx=10)
        self.msg = tk.Label(root, font=("Meiryo", 9), fg="#444", anchor="w", width=45)
        self.msg.pack(padx=10, pady=4)

        btns = tk.Frame(root, padx=10, pady=4)
        btns.pack(fill="x")
        for name in STATES:
            tk.Button(btns, text=name, width=7,
                      command=lambda n=name: self.manual(n)).pack(side="left", padx=2)

        bottom = tk.Frame(root, padx=10, pady=8)
        bottom.pack(fill="x")
        self.auto = tk.BooleanVar(value=True)
        tk.Checkbutton(bottom, text="自動モード", variable=self.auto,
                       command=self.on_auto_toggle).pack(side="left")
        tk.Button(bottom, text="この位置を config に設定",
                  command=self.write_config).pack(side="right")

        self.state = None
        self.timer = None
        self.progress_value = 0
        self.set_state("待機")
        self.schedule_next()
        self.animate()

    # --- 状態の切り替え ---
    def set_state(self, name):
        self.state = name
        self.lamp.config(bg=STATES[name])
        self.state_label.config(text=name, fg=STATES[name] if name != "エラー" else "#b08000")
        if name in ("待機", "進行中"):
            self.progress_value = 0
        if name == "完了":
            self.progress_value = 100
        self.msg.config(text={
            "待機": "機器の接続を待っています…",
            "進行中": "コンフィグを書き込んでいます…",
            "エラー": "通信エラーが発生しました。再試行します。",
            "完了": "コンフィグが完了しました。機器を外してください。",
        }[name])

    def next_state(self):
        if self.state == "待機":
            return "進行中"
        if self.state == "進行中":
            return "エラー" if random.random() < ERROR_RATE else "完了"
        if self.state == "エラー":
            return "進行中"
        return "待機"

    def schedule_next(self):
        if self.timer:
            self.root.after_cancel(self.timer)
            self.timer = None
        if self.auto.get():
            lo, hi = DURATION[self.state]
            self.timer = self.root.after(int(random.uniform(lo, hi) * 1000), self.auto_step)

    def auto_step(self):
        self.timer = None
        self.set_state(self.next_state())
        self.schedule_next()

    def manual(self, name):
        self.set_state(name)
        self.schedule_next()

    def on_auto_toggle(self):
        self.schedule_next()

    def animate(self):
        if self.state == "進行中":
            self.progress_value = min(99, self.progress_value + random.uniform(0.5, 2.5))
        self.progress.delete("all")
        width = 320 * self.progress_value / 100
        self.progress.create_rectangle(0, 0, width, 18, fill=STATES[self.state], width=0)
        self.root.after(200, self.animate)

    # --- 座標を config.json に保存 ---
    def write_config(self):
        self.root.update_idletasks()
        x = self.lamp.winfo_rootx() + self.lamp.winfo_width() // 2
        y = self.lamp.winfo_rooty() + self.lamp.winfo_height() // 2
        cfg = load_config()
        cfg["x"], cfg["y"] = x, y
        labels = dict(cfg.get("labels") or {})
        labels.update(DEMO_LABELS)
        cfg["labels"] = labels
        cfg["roles"] = DEMO_ROLES
        cfg["window_title"] = WINDOW_TITLE
        save_config(cfg)
        self.msg.config(text=f"config.json に保存しました: ({x}, {y})")


def main():
    set_dpi_aware()
    root = tk.Tk()
    DemoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
