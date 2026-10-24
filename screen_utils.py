"""画面ピクセル読み取りなど、2つのツールで共通の処理（Windows専用・追加ライブラリ不要）"""
import ctypes
import json
import os
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "x": 100,            # 色を読み取る座標 X
    "y": 100,            # 色を読み取る座標 Y
    "border": 25,        # 外周の枠の太さ (px)
    "interval_sec": 0.5  # 色を確認する間隔 (秒)
}

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [wintypes.HWND, ctypes.c_void_p]
gdi32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
gdi32.GetPixel.restype = wintypes.DWORD


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


def get_cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def to_hex(rgb):
    return "#%02x%02x%02x" % rgb


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
