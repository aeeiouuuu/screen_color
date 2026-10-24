"""色の変化ログを分析して、レポート (HTML) と集計表 (CSV) を出力する

  python analyze.py                          # logs/ を分析
  python analyze.py --log-dir sample_logs    # サンプルログを分析
  python analyze.py --log-dir \\\\server\\share\\logs   # 共有フォルダの全PC分を分析

出力先: reports/
  report_<日時>.html   … ブラウザで見るレポート (印刷→PDF保存も可)
  segments_<日時>.csv  … 色が続いた区間の一覧 (Excel用)
  summary_<日時>.csv   … PC × 色 の集計 (Excel用)
"""
import argparse
import csv
import html
import os
import webbrowser
from collections import defaultdict
from datetime import datetime
from statistics import mean

from color_log import build_segments, read_logs, resolve_log_dir
from screen_utils import CONFIG_PATH, load_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- 表示用ヘルパー
def fmt_dur(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}時間{m:02d}分"
    if m:
        return f"{m}分{s:02d}秒"
    return f"{s}秒"


def esc(s):
    return html.escape(str(s))


def text_color_for(hex_color):
    """背景色に対して読みやすい文字色 (黒 or 白)"""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#000" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#fff"


# ---------------------------------------------------------------- 集計
class Analysis:
    def __init__(self, segments, labels):
        self.segments = segments
        self.labels = labels
        self.pcs = sorted({s["pc"] for s in segments})
        self.days = sorted({s["start"].date() for s in segments})

        by_color = defaultdict(list)
        by_pc_color = defaultdict(list)
        for s in segments:
            by_color[s["color"]].append(s["seconds"])
            by_pc_color[(s["pc"], s["color"])].append(s["seconds"])
        self.by_color = by_color
        self.by_pc_color = by_pc_color
        # 合計時間の長い順
        self.colors = sorted(by_color, key=lambda c: -sum(by_color[c]))
        self.total_sec = sum(s["seconds"] for s in segments)

    def name(self, color):
        return self.labels.get(color, color)

    def insights(self):
        """PC 間で偏りがあるものを自動で拾う"""
        notes = []
        n_pc = len(self.pcs)
        if n_pc < 2:
            return notes
        for c in self.colors:
            counts = {pc: len(self.by_pc_color.get((pc, c), [])) for pc in self.pcs}
            avg_count = sum(counts.values()) / n_pc
            if avg_count >= 3:
                for pc, n in counts.items():
                    if n >= avg_count * 1.5:
                        notes.append((n / avg_count,
                                      f"<b>{esc(pc)}</b> は {self.chip(c)} の回数が "
                                      f"<b>{n}回</b>（全PC平均 {avg_count:.1f}回 の "
                                      f"<b>{n / avg_count:.1f}倍</b>）"))
            avgs = {pc: mean(v) for pc in self.pcs
                    if len(v := self.by_pc_color.get((pc, c), [])) >= 5}
            if len(avgs) >= 2:
                overall = mean(avgs.values())
                for pc, a in avgs.items():
                    if a >= overall * 1.2:
                        notes.append((a / overall,
                                      f"<b>{esc(pc)}</b> は {self.chip(c)} の平均時間が "
                                      f"<b>{fmt_dur(a)}</b>（全PC平均 {fmt_dur(overall)} より "
                                      f"<b>{(a / overall - 1) * 100:.0f}%長い</b>）"))
        notes.sort(key=lambda x: -x[0])
        return [n for _, n in notes]

    def chip(self, color):
        return (f'<span class="chip"><i style="background:{color}"></i>'
                f'{esc(self.name(color))}</span>')


# ---------------------------------------------------------------- HTML 部品
def section_summary(a):
    rows = []
    for c in a.colors:
        v = a.by_color[c]
        share = sum(v) / a.total_sec * 100 if a.total_sec else 0
        rows.append(f"""
        <tr><td>{a.chip(c)}</td><td class="mono">{c}</td>
          <td class="num">{len(v):,}</td><td class="num">{fmt_dur(sum(v))}</td>
          <td class="num">{fmt_dur(mean(v))}</td><td class="num">{fmt_dur(max(v))}</td>
          <td><div class="share"><div style="width:{share:.1f}%;background:{c}"></div></div>
              <span class="num">{share:.1f}%</span></td></tr>""")
    return f"""
    <section><h2>色ごとのまとめ</h2>
    <p class="note">全PC・全期間の合計です。「回数」はその色になった回数、「時間」はその色が続いた長さです。</p>
    <div class="scroll"><table>
      <thead><tr><th>色</th><th>コード</th><th>回数</th><th>合計時間</th><th>平均時間</th><th>最長</th><th>時間の割合</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table></div></section>"""


def section_pc_share(a):
    rows = []
    for pc in a.pcs:
        tot = sum(sum(a.by_pc_color.get((pc, c), [])) for c in a.colors)
        parts = []
        for c in a.colors:
            sec = sum(a.by_pc_color.get((pc, c), []))
            if not sec or not tot:
                continue
            pct = sec / tot * 100
            label = f"{pct:.0f}%" if pct >= 7 else ""
            parts.append(f'<div style="width:{pct:.2f}%;background:{c};color:{text_color_for(c)}" '
                         f'title="{esc(a.name(c))}: {fmt_dur(sec)} ({pct:.1f}%)">{label}</div>')
        rows.append(f'<div class="bar-row"><span class="bar-label">{esc(pc)}</span>'
                    f'<div class="stack">{"".join(parts)}</div>'
                    f'<span class="bar-total">{fmt_dur(tot)}</span></div>')
    legend = "".join(a.chip(c) for c in a.colors)
    return f"""
    <section><h2>PC別の時間の内訳</h2>
    <p class="note">各PCで、どの色の状態がどれくらいの割合を占めたか。右端は記録された合計時間。</p>
    <div class="legend">{legend}</div>
    <div class="bars">{''.join(rows)}</div></section>"""


def matrix_table(a, title, note, value_fn, fmt_fn):
    head = "".join(f"<th>{a.chip(c)}</th>" for c in a.colors)
    col_max = {c: max((value_fn(pc, c) or 0) for pc in a.pcs) or 1 for c in a.colors}
    body = []
    for pc in a.pcs:
        cells = []
        for c in a.colors:
            v = value_fn(pc, c)
            if v is None:
                cells.append('<td class="num muted">-</td>')
                continue
            alpha = 0.08 + 0.55 * (v / col_max[c])
            cells.append(f'<td class="num heat" style="--heat:{alpha:.2f}">{fmt_fn(v)}</td>')
        body.append(f"<tr><th class='rowh'>{esc(pc)}</th>{''.join(cells)}</tr>")
    return f"""
    <section><h2>{title}</h2><p class="note">{note}</p>
    <div class="scroll"><table class="matrix">
      <thead><tr><th>PC</th>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div></section>"""


def section_hourly(a):
    hours = sorted({s["start"].hour for s in a.segments})
    if not hours:
        return ""
    hours = list(range(hours[0], hours[-1] + 1))
    rows = []
    for c in a.colors:
        counts = defaultdict(int)
        for s in a.segments:
            if s["color"] == c:
                counts[s["start"].hour] += 1
        peak = max(counts.values()) or 1
        cols = "".join(
            f'<div class="hcol" title="{h}時台: {counts[h]}回">'
            f'<div class="hbar" style="height:{counts[h] / peak * 100:.0f}%;background:{c}"></div></div>'
            for h in hours)
        rows.append(f'<div class="hrow"><div class="hname">{a.chip(c)}</div>'
                    f'<div class="hcols">{cols}</div></div>')
    axis = "".join(f'<div class="hcol hlab">{h}</div>' for h in hours)
    return f"""
    <section><h2>時間帯ごとの発生回数</h2>
    <p class="note">その色になった回数を、時間帯（時）ごとに数えたもの（全PC・全期間の合計）。色ごとに一番多い時間帯を最大の高さにしています。</p>
    <div class="hourly">{''.join(rows)}
      <div class="hrow"><div class="hname"></div><div class="hcols">{axis}</div></div></div></section>"""


def section_daily(a):
    head = "".join(f"<th>{a.chip(c)}</th>" for c in a.colors)
    counts = defaultdict(int)
    for s in a.segments:
        counts[(s["start"].date(), s["color"])] += 1
    body = "".join(
        f"<tr><th class='rowh'>{d:%m/%d}（{'月火水木金土日'[d.weekday()]}）</th>"
        + "".join(f'<td class="num">{counts[(d, c)]:,}</td>' for c in a.colors) + "</tr>"
        for d in a.days)
    return f"""
    <section><h2>日別の回数</h2>
    <div class="scroll"><table class="matrix"><thead><tr><th>日付</th>{head}</tr></thead>
    <tbody>{body}</tbody></table></div></section>"""


def section_timeline(a, max_days=7):
    blocks = []
    for i, d in enumerate(reversed(a.days[-max_days:])):
        segs = [s for s in a.segments if s["start"].date() == d]
        t0 = min(s["start"] for s in segs).replace(minute=0, second=0)
        t1 = max(s["end"] for s in segs)
        span = max((t1 - t0).total_seconds(), 1)
        n_hours = int(span // 3600) + 1
        ticks = "".join(f'<span style="left:{h * 3600 / span * 100:.2f}%">{t0.hour + h}時</span>'
                        for h in range(n_hours) if h * 3600 <= span)
        rows = []
        for pc in a.pcs:
            bars = "".join(
                f'<i style="left:{(s["start"] - t0).total_seconds() / span * 100:.3f}%;'
                f'width:{s["seconds"] / span * 100:.3f}%;background:{s["color"]}" '
                f'title="{esc(a.name(s["color"]))} {s["start"]:%H:%M:%S}〜{s["end"]:%H:%M:%S} ({fmt_dur(s["seconds"])})"></i>'
                for s in segs if s["pc"] == pc)
            rows.append(f'<div class="tl-row"><span class="bar-label">{esc(pc)}</span>'
                        f'<div class="tl">{bars}</div></div>')
        blocks.append(f"""
        <details {'open' if i == 0 else ''}><summary>{d:%Y/%m/%d}（{'月火水木金土日'[d.weekday()]}）</summary>
          <div class="tl-wrap"><div class="tl-row"><span class="bar-label"></span>
            <div class="tl-axis">{ticks}</div></div>{''.join(rows)}</div></details>""")
    return f"""
    <section><h2>タイムライン</h2>
    <p class="note">各PCの色の移り変わり（直近{min(max_days, len(a.days))}日分）。色の帯にマウスを乗せると時刻が出ます。空白はログがない時間（監視停止中）です。</p>
    {''.join(blocks)}</section>"""


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--muted:#6b7280;--line:#e3e6eb;--heat-rgb:37,99,235;--accent:#2563eb}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14171c;--card:#1d2128;--fg:#e6e8ec;--muted:#9aa3b2;--line:#2e3440;--heat-rgb:96,165,250;--accent:#60a5fa}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:"Yu Gothic UI","Meiryo",system-ui,sans-serif;font-size:14px;line-height:1.6}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:0 0 6px}
.sub{color:var(--muted);margin:0 0 20px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:0 0 16px}
.note{color:var(--muted);font-size:12.5px;margin:0 0 12px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:0 0 16px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
.kpi b{display:block;font-size:22px;font-variant-numeric:tabular-nums} .kpi span{color:var(--muted);font-size:12px}
table{border-collapse:collapse;width:100%} th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
thead th{font-size:12px;color:var(--muted);font-weight:600}
.num{text-align:right;font-variant-numeric:tabular-nums} .mono{font-family:Consolas,monospace;color:var(--muted)} .muted{color:var(--muted)}
.heat{background:rgba(var(--heat-rgb),var(--heat))}
.rowh{font-weight:600}
.scroll{overflow-x:auto}
.chip{display:inline-flex;align-items:center;gap:6px;font-weight:600}
.chip i{width:12px;height:12px;border-radius:3px;display:inline-block;border:1px solid rgba(0,0,0,.25)}
.share{display:inline-block;width:120px;height:10px;background:var(--line);border-radius:5px;overflow:hidden;vertical-align:middle;margin-right:6px}
.share div{height:100%}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 10px}
.bar-row,.tl-row{display:flex;align-items:center;gap:10px;margin:5px 0}
.bar-label{width:96px;flex:none;font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis}
.stack{flex:1;display:flex;height:22px;border-radius:5px;overflow:hidden;background:var(--line)}
.stack div{font-size:11px;display:flex;align-items:center;justify-content:center;overflow:hidden}
.bar-total{width:80px;flex:none;text-align:right;color:var(--muted);font-size:12px}
.insights{margin:0;padding-left:20px} .insights li{margin:4px 0}
.hourly{overflow-x:auto} .hrow{display:flex;align-items:flex-end;gap:10px;min-width:560px}
.hname{width:110px;flex:none;padding-bottom:4px} .hcols{flex:1;display:flex;gap:3px;height:56px;align-items:flex-end;border-bottom:1px solid var(--line);margin:4px 0}
.hrow:last-child .hcols{height:auto;border:0}
.hcol{flex:1;height:100%;display:flex;align-items:flex-end} .hbar{width:100%;border-radius:2px 2px 0 0;min-height:1px}
.hlab{font-size:11px;color:var(--muted);justify-content:center;height:auto}
details{border-top:1px solid var(--line);padding:8px 0} summary{cursor:pointer;font-weight:600}
.tl-wrap{overflow-x:auto;padding:6px 0} .tl-wrap .tl-row{min-width:700px}
.tl{flex:1;position:relative;height:18px;background:var(--line);border-radius:3px}
.tl i{position:absolute;top:0;bottom:0}
.tl-axis{flex:1;position:relative;height:16px;font-size:11px;color:var(--muted)}
.tl-axis span{position:absolute;transform:translateX(-50%)}
.empty{color:var(--muted)}
@media print{body{background:#fff}section,.kpi{break-inside:avoid;border-color:#ccc}details{display:block}}
"""


def build_html(a, log_dir, generated):
    if not a.segments:
        body = f'<section><p class="empty">ログがありません（{esc(log_dir)}）。</p></section>'
        period = "-"
    else:
        period = f"{a.days[0]:%Y/%m/%d} 〜 {a.days[-1]:%Y/%m/%d}"
        insights = a.insights()
        ins_html = ("<ul class='insights'>" + "".join(f"<li>{n}</li>" for n in insights[:10]) + "</ul>"
                    if insights else '<p class="empty">PC間で目立った偏りはありませんでした。</p>')
        kpis = f"""
        <div class="kpis">
          <div class="kpi"><span>期間</span><b style="font-size:16px">{period}</b></div>
          <div class="kpi"><span>PC台数</span><b>{len(a.pcs)}台</b></div>
          <div class="kpi"><span>記録された時間（合計）</span><b>{fmt_dur(a.total_sec)}</b></div>
          <div class="kpi"><span>色が変わった回数</span><b>{len(a.segments):,}回</b></div>
        </div>"""
        body = (kpis
                + f'<section><h2>気づき（自動抽出）</h2><p class="note">ほかのPCと比べて回数が1.5倍以上、または平均時間が2割以上長いもの。</p>{ins_html}</section>'
                + section_summary(a)
                + section_pc_share(a)
                + matrix_table(a, "PC別の回数", "PCごとに、その色になった回数。色が濃いほど多い（列ごとに比較）。",
                               lambda pc, c: len(a.by_pc_color[(pc, c)]) if (pc, c) in a.by_pc_color else None,
                               lambda v: f"{v:,}")
                + matrix_table(a, "PC別の平均時間", "PCごとに、その色が1回あたり続いた平均時間。色が濃いほど長い（列ごとに比較）。",
                               lambda pc, c: mean(a.by_pc_color[(pc, c)]) if (pc, c) in a.by_pc_color else None,
                               fmt_dur)
                + section_hourly(a)
                + section_daily(a)
                + section_timeline(a))
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>コンフィグ状態レポート</title><style>{CSS}</style></head>
<body><main>
<h1>コンフィグ状態レポート</h1>
<p class="sub">ログ: {esc(log_dir)} ／ 作成: {generated:%Y/%m/%d %H:%M}</p>
{body}
</main></body></html>"""


# ---------------------------------------------------------------- CSV 出力
def write_csvs(a, out_dir, stamp):
    seg_path = os.path.join(out_dir, f"segments_{stamp}.csv")
    with open(seg_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["PC", "色", "名前", "開始", "終了", "秒数"])
        for s in a.segments:
            w.writerow([s["pc"], s["color"], a.name(s["color"]),
                        f"{s['start']:%Y-%m-%d %H:%M:%S}", f"{s['end']:%Y-%m-%d %H:%M:%S}",
                        int(s["seconds"])])

    sum_path = os.path.join(out_dir, f"summary_{stamp}.csv")
    with open(sum_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["PC", "色", "名前", "回数", "合計秒", "平均秒", "最長秒"])
        for pc in a.pcs:
            for c in a.colors:
                v = a.by_pc_color.get((pc, c))
                if v:
                    w.writerow([pc, c, a.name(c), len(v), int(sum(v)), int(mean(v)), int(max(v))])
    return seg_path, sum_path


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description="色の変化ログを分析してレポートを出力")
    ap.add_argument("--log-dir", default=resolve_log_dir(cfg, os.path.dirname(CONFIG_PATH)))
    ap.add_argument("--out-dir", default=os.path.join(BASE_DIR, "reports"))
    ap.add_argument("--no-open", action="store_true", help="レポートをブラウザで開かない")
    args = ap.parse_args()

    log_dir = args.log_dir if os.path.isabs(args.log_dir) else os.path.join(BASE_DIR, args.log_dir)
    if not os.path.isdir(log_dir):
        print(f"ログフォルダが見つかりません: {log_dir}")
        return

    a = Analysis(build_segments(read_logs(log_dir)), cfg.get("labels") or {})
    os.makedirs(args.out_dir, exist_ok=True)
    now = datetime.now()
    stamp = f"{now:%Y%m%d_%H%M%S}"

    report = os.path.join(args.out_dir, f"report_{stamp}.html")
    with open(report, "w", encoding="utf-8") as f:
        f.write(build_html(a, log_dir, now))
    seg_path, sum_path = write_csvs(a, args.out_dir, stamp)

    print(f"PC {len(a.pcs)}台 / 区間 {len(a.segments):,}件 を分析しました")
    print(f"  レポート: {report}")
    print(f"  CSV     : {seg_path}")
    print(f"            {sum_path}")
    if not args.no_open:
        webbrowser.open("file:///" + report.replace("\\", "/"))


if __name__ == "__main__":
    main()
