"""画面ピクセル読み取りなど、各ツールで共通の処理（Windows専用・追加ライブラリ不要）"""
import ctypes
import json
import os
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "x": 100,              # 色を読み取る座標 X
    "y": 100,              # 色を読み取る座標 Y
    "window_title": "",    # 対象ウィンドウのタイトル (一部でOK)。空なら確認しない
    "border": 25,          # 外周の枠の太さ (px)
    "interval_sec": 0.5,   # 色を確認する間隔 (秒)
    "stable_samples": 2,   # 同じ色が何回続いたら「変わった」とみなすか (ちらつき対策)
    "color_tolerance": 40, # labels の色との許容差 (0〜441)。labels が空なら使わない
    "pc_name": "",         # ログに記録するPC名 (空ならWindowsのコンピューター名)
    "log_dir": "logs",     # ログの保存先 (共有フォルダも指定可)
    "labels": {},          # 色の名前 (例: {"#0078d7": "進行中"})
    "roles": {}            # 分析で使う色の役割 (例: {"done": "完了", "error": "エラー"})
}

GA_ROOT = 2

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
gdi32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = wintypes.DWORD
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND


def set_dpi_aware():
    """拡大率の設定に関係なく、実際のピクセル座標で扱うようにする"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def get_pixel(x, y):
    """画面上 (x, y) の色を (R, G, B) で返す。読めなければ None"""
    hdc = user32.GetDC(None)
    try:
        c = gdi32.GetPixel(hdc, x, y)
    finally:
        user32.ReleaseDC(None, hdc)
    if c == 0xFFFFFFFF:
        return None
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


def window_title_at(x, y):
    """画面上 (x, y) に一番手前に表示されているウィンドウのタイトル"""
    hwnd = user32.WindowFromPoint(wintypes.POINT(x, y))
    if not hwnd:
        return ""
    root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(root, buf, 512)
    return buf.value


def get_cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def to_hex(rgb):
    return "#%02x%02x%02x" % rgb


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def nearest_label_color(rgb, labels, tolerance):
    """labels の中で一番近い色コードを返す。許容差を超えたら None"""
    best, best_d = None, None
    for code in labels:
        d = sum((a - b) ** 2 for a, b in zip(rgb, hex_to_rgb(code))) ** 0.5
        if best_d is None or d < best_d:
            best, best_d = code.lower(), d
    return best if best_d is not None and best_d <= tolerance else None


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
