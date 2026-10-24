"""色の変化ログを分析して、レポート (HTML) と集計表 (CSV) を出力する

  python analyze.py                          # logs/ を分析
  python analyze.py --log-dir sample_logs    # サンプルログを分析
  python analyze.py --log-dir \\\\server\\share\\logs   # 共有フォルダの全PC分を分析

出力先: reports/
  report_<日時>.html   … ブラウザで見るレポート。期間・PCで絞り込める (印刷→PDF保存も可)
  segments_<日時>.csv  … 色が続いた区間の一覧 (Excel用)
  summary_<日時>.csv   … PC × 色 の集計 (Excel用)

config.json の roles に「完了」「エラー」の色を指定すると、処理台数・エラー率・
対応待ち時間を分析します。
"""
import argparse
import calendar
import csv
import json
import os
import webbrowser
from collections import defaultdict
from datetime import datetime
from statistics import mean

from color_log import build_segments, read_logs, resolve_log_dir
from screen_utils import CONFIG_PATH, load_config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def epoch(dt):
    """ローカル時刻をそのまま秒に (レポート側も UTC として扱うので時差がずれない)"""
    return calendar.timegm(dt.timetuple())


def resolve_role(value, labels):
    """roles の値 (色の名前 or 色コード) を色コードにする"""
    if not value:
        return None
    if value.lower() in labels:
        return value.lower()
    for code, name in labels.items():
        if name == value:
            return code
    return None


def add_cycles(segments, done_color):
    """完了の区間に「前の完了からの時間 (サイクルタイム)」を付ける。同じセッション内のみ"""
    last = {}
    for s in sorted(segments, key=lambda s: (s["pc"], s["start"])):
        s["cycle"] = 0
        if s["color"] != done_color:
            continue
        key = (s["pc"], s["session"])
        if key in last:
            s["cycle"] = (s["start"] - last[key]).total_seconds()
        last[key] = s["start"]


def build_data(segments, hides, labels, roles, log_dir, generated):
    totals = defaultdict(float)
    for s in segments:
        totals[s["color"]] += s["seconds"]
    colors = sorted(totals, key=lambda c: -totals[c])
    cidx = {c: i for i, c in enumerate(colors)}
    pcs = sorted({s["pc"] for s in segments})
    pidx = {p: i for i, p in enumerate(pcs)}
    return {
        "generated": generated.strftime("%Y/%m/%d %H:%M"),
        "logDir": log_dir,
        "pcs": pcs,
        "colors": [{"hex": c, "name": labels.get(c, c)} for c in colors],
        "roles": {k: cidx.get(v, -1) for k, v in roles.items()},
        # [PC, 色, 開始, 秒数, 見えなかった秒数, サイクル秒数]
        "segs": [[pidx[s["pc"]], cidx[s["color"]], epoch(s["start"]), round(s["seconds"]),
                  round(s["hidden"]), round(s.get("cycle", 0))] for s in segments],
        "hides": [[pidx[h["pc"]], epoch(h["start"]), epoch(h["end"])]
                  for h in hides if h["pc"] in pidx],
    }


def write_csvs(segments, labels, out_dir, stamp):
    seg_path = os.path.join(out_dir, f"segments_{stamp}.csv")
    with open(seg_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["PC", "色", "名前", "開始", "終了", "秒数", "見えなかった秒数", "サイクル秒数"])
        for s in segments:
            w.writerow([s["pc"], s["color"], labels.get(s["color"], ""),
                        f"{s['start']:%Y-%m-%d %H:%M:%S}", f"{s['end']:%Y-%m-%d %H:%M:%S}",
                        int(s["seconds"]), int(s["hidden"]), int(s.get("cycle", 0))])

    groups = defaultdict(list)
    for s in segments:
        groups[(s["pc"], s["color"])].append(s["seconds"])
    sum_path = os.path.join(out_dir, f"summary_{stamp}.csv")
    with open(sum_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["PC", "色", "名前", "回数", "合計秒", "平均秒", "最長秒"])
        for (pc, c), v in sorted(groups.items()):
            w.writerow([pc, c, labels.get(c, ""), len(v), int(sum(v)), int(mean(v)), int(max(v))])
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

    labels = {k.lower(): v for k, v in (cfg.get("labels") or {}).items()}
    roles = {k: resolve_role(v, labels) for k, v in (cfg.get("roles") or {}).items()}
    roles = {k: v for k, v in roles.items() if v}
    if not roles.get("done"):
        print("注意: config.json の roles に done (完了の色) がないため、処理台数などは分析しません。")

    segments, hides = build_segments(read_logs(log_dir))
    add_cycles(segments, roles.get("done"))

    now = datetime.now()
    stamp = f"{now:%Y%m%d_%H%M%S}"
    os.makedirs(args.out_dir, exist_ok=True)

    data = build_data(segments, hides, labels, roles, log_dir, now)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    report = os.path.join(args.out_dir, f"report_{stamp}.html")
    with open(report, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.replace("__DATA__", payload))
    seg_path, sum_path = write_csvs(segments, labels, args.out_dir, stamp)

    print(f"PC {len(data['pcs'])}台 / 区間 {len(segments):,}件 を分析しました")
    print(f"  レポート: {report}")
    print(f"  CSV     : {seg_path}")
    print(f"            {sum_path}")
    if not args.no_open:
        webbrowser.open("file:///" + report.replace("\\", "/"))


# ---------------------------------------------------------------- レポートの HTML
# 集計と描画はブラウザ側 (JavaScript) で行うので、期間・PC の絞り込みがその場でできる
TEMPLATE = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>コンフィグ状態レポート</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--muted:#6b7280;--line:#e3e6eb;--heat-rgb:37,99,235;--accent:#2563eb;--btn:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--fg:#e6e8ec;--muted:#9aa3b2;--line:#2e3440;--heat-rgb:96,165,250;--accent:#60a5fa;--btn:#2a303a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:"Yu Gothic UI","Meiryo",system-ui,sans-serif;font-size:14px;line-height:1.6}
main,.top{max-width:1120px;margin:0 auto;padding:0 16px}
header{padding:22px 0 10px} h1{font-size:22px;margin:0} .sub{color:var(--muted);margin:2px 0 0;font-size:12.5px}
h2{font-size:17px;margin:0 0 6px} h3{font-size:14px;margin:12px 0 6px}
.filters{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 0;margin-bottom:16px}
.frow{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:3px 0}
.flabel{width:40px;font-weight:700;color:var(--muted);font-size:12px}
button{font:inherit;font-size:12.5px;border:1px solid var(--line);background:var(--btn);color:var(--fg);border-radius:6px;padding:3px 10px;cursor:pointer}
button:hover{border-color:var(--accent)} button.on{background:var(--accent);border-color:var(--accent);color:#fff}
input[type=date]{font:inherit;font-size:12.5px;padding:2px 6px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--fg)}
.sep{width:1px;height:20px;background:var(--line);margin:0 6px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:0 0 16px}
.note{color:var(--muted);font-size:12.5px;margin:0 0 12px}
.warn{border-left:4px solid #f59e0b}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:0 0 16px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px}
.kpi b{display:block;font-size:22px;font-variant-numeric:tabular-nums;line-height:1.3} .kpi span{color:var(--muted);font-size:12px} .kpi small{color:var(--muted);font-size:11.5px}
table{border-collapse:collapse;width:100%} th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
thead th{font-size:12px;color:var(--muted);font-weight:600;vertical-align:bottom} tfoot td,tfoot th{font-weight:700;border-top:2px solid var(--line)}
.num{text-align:right;font-variant-numeric:tabular-nums} .muted{color:var(--muted)}
.heat{background:rgba(var(--heat-rgb),var(--heat))} .rowh{font-weight:600}
.scroll{overflow-x:auto}
.chip{display:inline-flex;align-items:center;gap:6px;font-weight:600}
.chip i{width:12px;height:12px;border-radius:3px;display:inline-block;border:1px solid rgba(0,0,0,.25)}
.share{display:inline-block;width:120px;height:10px;background:var(--line);border-radius:5px;overflow:hidden;vertical-align:middle;margin-right:6px} .share div{height:100%}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 10px}
.bar-row,.tl-row{display:flex;align-items:center;gap:10px;margin:5px 0}
.bar-label{width:96px;flex:none;font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis}
.stack{flex:1;display:flex;height:22px;border-radius:5px;overflow:hidden;background:var(--line)}
.stack div{font-size:11px;display:flex;align-items:center;justify-content:center;overflow:hidden}
.bar-total{width:80px;flex:none;text-align:right;color:var(--muted);font-size:12px}
.insights{margin:0;padding-left:20px} .insights li{margin:4px 0}
.vchart{display:flex;align-items:flex-end;gap:6px;overflow-x:auto;padding-top:4px}
.vcol{flex:1;min-width:34px;display:flex;flex-direction:column;align-items:center}
.vval{font-size:12px;font-weight:700;font-variant-numeric:tabular-nums}
.vbar{width:70%;border-radius:3px 3px 0 0;min-height:1px}
.vlab{font-size:11px;color:var(--muted);border-top:1px solid var(--line);width:100%;text-align:center;padding-top:2px;line-height:1.3}
.hourly{overflow-x:auto} .hrow{display:flex;align-items:flex-end;gap:10px;min-width:640px;margin:2px 0}
.hname{width:150px;flex:none;font-size:12.5px;font-weight:600;padding-bottom:2px}
.hcols{flex:1;display:flex;gap:3px;align-items:flex-end;border-bottom:1px solid var(--line)}
.hcol{flex:1;height:72px;display:flex;flex-direction:column;justify-content:flex-end;align-items:center}
.hval{font-size:10px;color:var(--muted);font-variant-numeric:tabular-nums;line-height:1.2}
.hbar{width:100%;border-radius:2px 2px 0 0}
.haxis .hcols{border:0} .haxis .hcol{height:auto;font-size:11px;color:var(--muted)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}
.dist{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:12.5px}
.dist .dl{width:64px;flex:none;color:var(--muted)} .dist .db{flex:1;height:14px;background:var(--line);border-radius:3px;overflow:hidden} .dist .db div{height:100%}
.dist .dn{width:96px;flex:none;text-align:right;font-variant-numeric:tabular-nums}
details{border-top:1px solid var(--line);padding:8px 0} summary{cursor:pointer;font-weight:600}
.tl-wrap{overflow-x:auto;padding:6px 0} .tl-wrap .tl-row{min-width:720px}
.tl{flex:1;position:relative;height:18px;background:var(--line);border-radius:3px}
.tl i,.tl b{position:absolute;top:0;bottom:0}
.tl b,.hidchip i{background:repeating-linear-gradient(45deg,rgba(0,0,0,.65) 0 3px,rgba(255,255,255,.35) 3px 6px)}
.tl-axis{flex:1;position:relative;height:16px;font-size:11px;color:var(--muted)} .tl-axis span{position:absolute;transform:translateX(-50%)}
.empty{color:var(--muted)}
@media print{body{background:#fff}.filters{position:static}.filters button,.filters input{display:none}section,.kpi{break-inside:avoid;border-color:#ccc}}
</style></head>
<body>
<div class="top">
  <header><h1>コンフィグ状態レポート</h1><p class="sub" id="sub"></p></header>
  <div class="filters">
    <div class="frow"><span class="flabel">期間</span>
      <input type="date" id="from"> 〜 <input type="date" id="to">
      <span class="sep"></span>
      <button data-q="last">最新日</button><button data-q="7">直近7日</button><button data-q="30">直近30日</button><button data-q="all">全期間</button>
      <span class="muted" id="range"></span></div>
    <div class="frow"><span class="flabel">PC</span><span id="pcbtns"></span>
      <span class="sep"></span><button id="pcall">全て</button><button id="pcnone">解除</button></div>
  </div>
</div>
<main id="main"></main>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const DAY = 86400, WD = '日月火水木金土';
const $ = s => document.querySelector(s);
const pad = n => String(n).padStart(2, '0');
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const sum = a => a.reduce((x, y) => x + y, 0);
const avg = a => a.length ? sum(a) / a.length : null;
const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
function fmtDur(sec) {
  if (sec == null) return '-';
  sec = Math.round(sec); const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return h ? `${h}時間${pad(m)}分` : m ? `${m}分${pad(s)}秒` : `${s}秒`;
}
const fmtMin = s => s == null ? '' : s >= 60 ? (s / 60).toFixed(1) + '分' : Math.round(s) + '秒';
const fmtNum = (v, d = 1) => v == null || !isFinite(v) ? '-' : v.toFixed(d);
const dayOf = t => Math.floor(t / DAY);
const dateOf = k => new Date(k * DAY * 1000);
const dayStr = k => { const d = dateOf(k); return `${d.getUTCMonth() + 1}/${d.getUTCDate()}（${WD[d.getUTCDay()]}）`; };
const dayISO = k => dateOf(k).toISOString().slice(0, 10);
const hm = t => { const d = new Date(t * 1000); return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`; };
const hms = t => { const d = new Date(t * 1000); return `${hm(t)}:${pad(d.getUTCSeconds())}`; };
const hourOf = t => Math.floor(t % DAY / 3600);
const textOn = hex => { const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16); return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#000' : '#fff'; };

const SEG = D.segs.map(s => ({pc: s[0], c: s[1], t: s[2], d: s[3], h: s[4], cyc: s[5], day: dayOf(s[2])}));
const HID = D.hides.map(h => ({pc: h[0], t: h[1], e: h[2], day: dayOf(h[1])}));
const DAYS = [...new Set(SEG.map(s => s.day))].sort((a, b) => a - b);
const DONE = D.roles.done ?? -1, ERR = D.roles.error ?? -1;
const HEX = i => D.colors[i].hex;
const chip = i => `<span class="chip"><i style="background:${HEX(i)}"></i>${esc(D.colors[i].name)}</span>`;
const PCN = i => esc(D.pcs[i]);
const HIDCHIP = '<span class="chip hidchip"><i></i>見えていない</span>';

const st = {from: DAYS[0], to: DAYS[DAYS.length - 1], pcs: new Set(D.pcs.map((_, i) => i))};

// ------------------------------------------------------------ 集計
function compute() {
  const segs = SEG.filter(s => st.pcs.has(s.pc) && s.day >= st.from && s.day <= st.to);
  const hides = HID.filter(h => st.pcs.has(h.pc) && h.day >= st.from && h.day <= st.to);
  const pcs = [...st.pcs].sort((a, b) => a - b);
  const days = [...new Set(segs.map(s => s.day))].sort((a, b) => a - b);
  const per = new Map(pcs.map(p => [p, {pc: p, mon: 0, hid: 0, done: 0, err: 0, cyc: [], errW: [], doneW: [], byColor: new Map()}]));
  for (const s of segs) {
    const p = per.get(s.pc);
    p.mon += s.d; p.hid += s.h;
    if (!p.byColor.has(s.c)) p.byColor.set(s.c, []);
    p.byColor.get(s.c).push(s.d);
    if (s.c === DONE) { p.done++; p.doneW.push(s.d); if (s.cyc > 0) p.cyc.push(s.cyc); }
    if (s.c === ERR) { p.err++; p.errW.push(s.d); }
  }
  const all = {mon: 0, hid: 0, done: 0, err: 0, cyc: [], errW: [], doneW: []};
  for (const p of per.values()) {
    all.mon += p.mon; all.hid += p.hid; all.done += p.done; all.err += p.err;
    all.cyc.push(...p.cyc); all.errW.push(...p.errW); all.doneW.push(...p.doneW);
  }
  return {segs, hides, pcs, days, per, all};
}
const rate = p => p.mon ? p.done / (p.mon / 3600) : null;      // 1時間あたり処理台数
const errRate = p => p.done ? p.err / p.done * 100 : null;    // 100台あたりエラー件数

// ------------------------------------------------------------ 各セクション
function kpis(c) {
  const k = (label, value, small = '') => `<div class="kpi"><span>${label}</span><b>${value}</b>${small ? `<small>${small}</small>` : ''}</div>`;
  const hidPct = c.all.mon ? c.all.hid / c.all.mon * 100 : 0;
  const out = [];
  if (DONE >= 0) {
    out.push(k('処理台数', `${c.all.done.toLocaleString()}台`, `1日平均 ${fmtNum(c.all.done / Math.max(c.days.length, 1))}台`));
    out.push(k('処理ペース', `${fmtNum(rate(c.all))}台/時`, 'PC1台・稼働1時間あたり'));
    out.push(k('サイクルタイム', fmtDur(median(c.all.cyc)), '完了→次の完了（中央値）'));
    if (ERR >= 0) out.push(k('エラー率', `${fmtNum(errRate(c.all))}件`, `100台あたり（計 ${c.all.err}件）`));
    if (ERR >= 0) out.push(k('エラー対応待ち', fmtDur(avg(c.all.errW)), 'エラー表示が続いた平均'));
    out.push(k('取り外し待ち', fmtDur(avg(c.all.doneW)), '完了表示が続いた平均'));
  } else {
    out.push(k('記録時間', fmtDur(c.all.mon)), k('色が変わった回数', `${c.segs.length.toLocaleString()}回`));
  }
  out.push(k('見えなかった時間', `${fmtNum(hidPct)}%`, fmtDur(c.all.hid)));
  return `<div class="kpis">${out.join('')}</div>`;
}

function insights(c) {
  const rows = c.pcs.map(p => c.per.get(p)).filter(p => p.mon > 0);
  const out = [];
  if (rows.length >= 2) {
    if (DONE >= 0) {
      const busy = rows.filter(p => p.mon >= 3600), a = avg(busy.map(rate));
      for (const p of busy) if (rate(p) < a * 0.85)
        out.push([a / rate(p), `<b>${PCN(p.pc)}</b> は処理ペースが <b>${fmtNum(rate(p))}台/時</b>（全PC平均 ${fmtNum(a)}台/時 の <b>${(rate(p) / a * 100).toFixed(0)}%</b>）`]);
    }
    if (DONE >= 0 && ERR >= 0) {
      const v = rows.filter(p => p.done >= 10), a = avg(v.map(errRate));
      for (const p of v) if (a > 0 && p.err >= 3 && errRate(p) >= a * 1.5)
        out.push([errRate(p) / a, `<b>${PCN(p.pc)}</b> はエラー率が <b>100台あたり${fmtNum(errRate(p))}件</b>（全PC平均 ${fmtNum(a)}件 の <b>${(errRate(p) / a).toFixed(1)}倍</b>）`]);
    }
    for (const [key, label, ok] of [['errW', 'エラー対応待ち', ERR >= 0], ['doneW', '取り外し待ち', DONE >= 0]]) {
      if (!ok) continue;
      const v = rows.filter(p => p[key].length >= 5), a = avg(v.map(p => avg(p[key])));
      for (const p of v) { const m = avg(p[key]); if (m >= a * 1.3)
        out.push([m / a, `<b>${PCN(p.pc)}</b> は${label}が平均 <b>${fmtDur(m)}</b>（全PC平均 ${fmtDur(a)} より <b>${((m / a - 1) * 100).toFixed(0)}%長い</b>）`]); }
    }
    if (DONE < 0) {
      for (let ci = 0; ci < D.colors.length; ci++) {
        const cnt = rows.map(p => (p.byColor.get(ci) || []).length), a = avg(cnt);
        rows.forEach((p, i) => { if (a >= 3 && cnt[i] >= a * 1.5)
          out.push([cnt[i] / a, `<b>${PCN(p.pc)}</b> は ${chip(ci)} の回数が <b>${cnt[i]}回</b>（全PC平均 ${fmtNum(a)}回 の <b>${(cnt[i] / a).toFixed(1)}倍</b>）`]); });
      }
    }
  }
  for (const p of rows) { const r = p.hid / p.mon; if (r >= 0.03)
    out.push([1 + r, `<b>${PCN(p.pc)}</b> は対象が見えなかった時間が <b>${fmtNum(r * 100)}%</b>（${fmtDur(p.hid)}）。コンフィグ画面の上に他のウィンドウが重なっていないか確認を`]); }
  out.sort((x, y) => y[0] - x[0]);
  const body = out.length ? `<ul class="insights">${out.slice(0, 12).map(x => `<li>${x[1]}</li>`).join('')}</ul>` : '<p class="empty">目立った偏りはありませんでした。</p>';
  return `<section><h2>気づき（自動抽出）</h2><p class="note">ほかのPCと比べて差が大きいもの（処理ペース85%未満・エラー率1.5倍以上・待ち時間3割以上長い・見えなかった時間3%以上）。</p>${body}</section>`;
}

function noRoles() {
  return `<section class="warn"><h2>処理台数・対応待ち時間の分析</h2><p class="note" style="margin:0">config.json の <code>roles</code> に完了とエラーの色を指定すると表示されます。例：<code>"roles": {"done": "完了", "error": "エラー"}</code></p></section>`;
}

function pcTable(c) {
  const cols = [
    ['処理台数', p => p.done, v => v.toLocaleString()],
    ['台/時', rate, v => fmtNum(v)],
    ['サイクル<br>（中央値）', p => median(p.cyc), fmtDur],
  ];
  if (ERR >= 0) cols.push(['エラー<br>回数', p => p.err, v => v.toLocaleString()], ['エラー率<br>（100台あたり）', errRate, v => fmtNum(v)],
                          ['エラー対応待ち<br>平均', p => avg(p.errW), fmtDur], ['エラー対応待ち<br>最長', p => p.errW.length ? Math.max(...p.errW) : null, fmtDur]);
  cols.push(['取り外し待ち<br>平均', p => avg(p.doneW), fmtDur], ['取り外し待ち<br>最長', p => p.doneW.length ? Math.max(...p.doneW) : null, fmtDur],
            ['見えなかった<br>時間', p => p.mon ? p.hid / p.mon * 100 : null, v => fmtNum(v) + '%']);
  const rows = c.pcs.map(p => c.per.get(p));
  const max = cols.map(([, f]) => Math.max(0, ...rows.map(f).filter(v => v != null)) || 1);
  const body = rows.map(p => `<tr><th class="rowh">${PCN(p.pc)}</th>${cols.map(([, f, fmt], i) => {
    const v = f(p); return v == null ? '<td class="num muted">-</td>' : `<td class="num heat" style="--heat:${(0.05 + 0.5 * v / max[i]).toFixed(2)}">${fmt(v)}</td>`; }).join('')}</tr>`).join('');
  const foot = `<tr><th>全体</th>${cols.map(([, f, fmt]) => { const v = f(c.all); return `<td class="num">${v == null ? '-' : fmt(v)}</td>`; }).join('')}</tr>`;
  return `<section><h2>PC別の比較</h2><p class="note">色が濃いほど値が大きい（列ごとに比較）。台/時 は稼働1時間あたりの処理台数。待ち時間は「エラー」「完了」の表示が続いた時間で、人が対応するまでの時間の目安です。</p>
    <div class="scroll"><table><thead><tr><th>PC</th>${cols.map(x => `<th class="num">${x[0]}</th>`).join('')}</tr></thead><tbody>${body}</tbody><tfoot>${foot}</tfoot></table></div></section>`;
}

function daily(c) {
  const useDone = DONE >= 0;
  const vals = c.days.map(d => {
    const s = c.segs.filter(x => x.day === d);
    const done = s.filter(x => x.c === DONE).length, err = s.filter(x => x.c === ERR).length;
    return {d, v: useDone ? done : s.length, er: done ? err / done * 100 : null};
  });
  const max = Math.max(1, ...vals.map(x => x.v)), color = useDone ? HEX(DONE) : 'var(--accent)';
  const cols = vals.map(x => `<div class="vcol" title="${dayStr(x.d)}: ${x.v}${useDone ? '台' : '回'}"><span class="vval">${x.v}</span>
      <div class="vbar" style="height:${(x.v / max * 140).toFixed(0)}px;background:${color}"></div>
      <span class="vlab">${dayStr(x.d)}${useDone && ERR >= 0 ? `<br>エラー率 ${fmtNum(x.er)}` : ''}</span></div>`).join('');
  return `<section><h2>日別の${useDone ? '処理台数' : '色が変わった回数'}</h2><p class="note">選択中のPCの合計。${useDone && ERR >= 0 ? 'エラー率は100台あたりの件数。' : ''}</p><div class="vchart">${cols}</div></section>`;
}

function waits(c) {
  const B = [[0, 60, '〜1分'], [60, 180, '1〜3分'], [180, 300, '3〜5分'], [300, 600, '5〜10分'], [600, Infinity, '10分以上']];
  const dist = (list, color) => {
    const n = B.map(([a, b]) => list.filter(v => v >= a && v < b).length), m = Math.max(1, ...n);
    return B.map(([, , l], i) => `<div class="dist"><span class="dl">${l}</span><div class="db"><div style="width:${n[i] / m * 100}%;background:${color}"></div></div>
      <span class="dn">${n[i]}回 (${list.length ? (n[i] / list.length * 100).toFixed(0) : 0}%)</span></div>`).join('');
  };
  const panels = [];
  if (ERR >= 0) panels.push(`<div><h3>${chip(ERR)} 対応待ち（エラー表示が続いた時間）</h3>${dist(c.all.errW, HEX(ERR))}<p class="note">平均 ${fmtDur(avg(c.all.errW))} ／ 中央値 ${fmtDur(median(c.all.errW))}</p></div>`);
  panels.push(`<div><h3>${chip(DONE)} 取り外し待ち（完了表示が続いた時間）</h3>${dist(c.all.doneW, HEX(DONE))}<p class="note">平均 ${fmtDur(avg(c.all.doneW))} ／ 中央値 ${fmtDur(median(c.all.doneW))}</p></div>`);
  const top = c.segs.filter(s => s.c === ERR || s.c === DONE).sort((a, b) => b.d - a.d).slice(0, 10);
  const rows = top.map(s => `<tr><td>${dayStr(s.day)} ${hm(s.t)}</td><th class="rowh">${PCN(s.pc)}</th><td>${chip(s.c)}</td><td class="num">${fmtDur(s.d)}</td>
    <td class="num muted">${s.h ? `うち見えなかった ${fmtDur(s.h)}` : ''}</td></tr>`).join('');
  return `<section><h2>対応待ち時間</h2><p class="note">「エラー」「完了」になってから次の状態に変わるまでの時間 ＝ 人が気づいて対応するまでの時間の目安。外周の色表示の効果測定にも使えます。</p>
    <div class="grid2">${panels.join('')}</div>
    <h3>待ち時間が長かった上位10件</h3><div class="scroll"><table><thead><tr><th>日時</th><th>PC</th><th>状態</th><th class="num">長さ</th><th></th></tr></thead><tbody>${rows || '<tr><td class="empty">なし</td></tr>'}</tbody></table></div></section>`;
}

function hourly(c) {
  if (!c.segs.length) return '';
  const hs = c.segs.map(s => hourOf(s.t)), h0 = Math.min(...hs), h1 = Math.max(...hs);
  const hours = Array.from({length: h1 - h0 + 1}, (_, i) => h0 + i);
  const by = hours.map(h => c.segs.filter(s => hourOf(s.t) === h));
  const nd = Math.max(c.days.length, 1);
  const row = (label, vals, color, fmt) => {
    const m = Math.max(0, ...vals.filter(v => v != null)) || 1;
    return `<div class="hrow"><div class="hname">${label}</div><div class="hcols">${vals.map((v, i) => `<div class="hcol" title="${hours[i]}時台: ${v == null ? '-' : fmt(v)}">
      <span class="hval">${v == null ? '' : fmt(v)}</span><div class="hbar" style="height:${v == null ? 0 : (v / m * 52).toFixed(1)}px;background:${color}"></div></div>`).join('')}</div></div>`;
  };
  const rows = [];
  if (DONE >= 0) {
    rows.push(row('処理台数（1日平均）', by.map(s => s.filter(x => x.c === DONE).length / nd), HEX(DONE), v => fmtNum(v)));
    if (ERR >= 0) {
      rows.push(row('エラー率（100台あたり）', by.map(s => { const d = s.filter(x => x.c === DONE).length; return d ? s.filter(x => x.c === ERR).length / d * 100 : null; }), HEX(ERR), v => fmtNum(v)));
      rows.push(row('エラー対応待ち（平均）', by.map(s => avg(s.filter(x => x.c === ERR).map(x => x.d))), HEX(ERR), fmtMin));
    }
    rows.push(row('取り外し待ち（平均）', by.map(s => avg(s.filter(x => x.c === DONE).map(x => x.d))), HEX(DONE), fmtMin));
  } else {
    D.colors.forEach((_, ci) => rows.push(row(chip(ci) + '（回数）', by.map(s => s.filter(x => x.c === ci).length), HEX(ci), v => String(v))));
  }
  const axis = `<div class="hrow haxis"><div class="hname"></div><div class="hcols">${hours.map(h => `<div class="hcol">${h}時</div>`).join('')}</div></div>`;
  return `<section><h2>時間帯別</h2><p class="note">その状態が始まった時刻で時間帯に分けています。休憩前後や夕方に悪化していないかの確認に。</p><div class="hourly">${rows.join('')}${axis}</div></section>`;
}

function colorSummary(c) {
  const tot = sum(c.segs.map(s => s.d)) || 1;
  const rows = D.colors.map((col, ci) => {
    const v = c.segs.filter(s => s.c === ci).map(s => s.d);
    if (!v.length) return '';
    const share = sum(v) / tot * 100;
    return `<tr><td>${chip(ci)}</td><td class="muted">${col.hex}</td><td class="num">${v.length.toLocaleString()}</td><td class="num">${fmtDur(sum(v))}</td>
      <td class="num">${fmtDur(avg(v))}</td><td class="num">${fmtDur(Math.max(...v))}</td>
      <td><div class="share"><div style="width:${share.toFixed(1)}%;background:${col.hex}"></div></div><span class="num">${share.toFixed(1)}%</span></td></tr>`;
  }).join('');
  return `<section><h2>色ごとのまとめ</h2><div class="scroll"><table>
    <thead><tr><th>色</th><th>コード</th><th class="num">回数</th><th class="num">合計時間</th><th class="num">平均時間</th><th class="num">最長</th><th>時間の割合</th></tr></thead>
    <tbody>${rows}</tbody></table></div></section>`;
}

function pcShare(c) {
  const rows = c.pcs.map(pc => {
    const p = c.per.get(pc), tot = p.mon;
    const parts = D.colors.map((col, ci) => {
      const sec = sum(p.byColor.get(ci) || []); if (!sec || !tot) return '';
      const pct = sec / tot * 100;
      return `<div style="width:${pct.toFixed(2)}%;background:${col.hex};color:${textOn(col.hex)}" title="${esc(col.name)}: ${fmtDur(sec)} (${pct.toFixed(1)}%)">${pct >= 7 ? pct.toFixed(0) + '%' : ''}</div>`;
    }).join('');
    return `<div class="bar-row"><span class="bar-label">${PCN(pc)}</span><div class="stack">${parts}</div><span class="bar-total">${fmtDur(tot)}</span></div>`;
  }).join('');
  return `<section><h2>PC別の時間の内訳</h2><p class="note">各PCで、どの状態がどれくらいの割合を占めたか。右端は記録された合計時間。</p>
    <div class="legend">${D.colors.map((_, i) => chip(i)).join('')}</div>${rows}</section>`;
}

function detailMatrix(c) {
  const head = D.colors.map((_, i) => `<th class="num">${chip(i)}</th>`).join('');
  const tbl = (f, fmt) => c.pcs.map(pc => { const p = c.per.get(pc);
    return `<tr><th class="rowh">${PCN(pc)}</th>${D.colors.map((_, ci) => { const v = p.byColor.get(ci); return `<td class="num">${v ? fmt(f(v)) : '-'}</td>`; }).join('')}</tr>`; }).join('');
  return `<section><details><summary>詳細：PC × 色 の回数・平均時間</summary>
    <h3>回数</h3><div class="scroll"><table><thead><tr><th>PC</th>${head}</tr></thead><tbody>${tbl(v => v.length, v => v.toLocaleString())}</tbody></table></div>
    <h3>平均時間</h3><div class="scroll"><table><thead><tr><th>PC</th>${head}</tr></thead><tbody>${tbl(avg, fmtDur)}</tbody></table></div></details></section>`;
}

function timeline(c, maxDays = 7) {
  const days = [...c.days].reverse().slice(0, maxDays);
  const blocks = days.map((d, i) => {
    const segs = c.segs.filter(s => s.day === d), hides = c.hides.filter(h => h.day === d);
    const t0 = Math.floor(Math.min(...segs.map(s => s.t)) / 3600) * 3600;
    const span = Math.max(Math.max(...segs.map(s => s.t + s.d)) - t0, 1);
    const pos = (t, len) => `left:${((t - t0) / span * 100).toFixed(3)}%;width:${(len / span * 100).toFixed(3)}%`;
    const ticks = []; for (let h = 0; h * 3600 <= span; h++) ticks.push(`<span style="left:${(h * 3600 / span * 100).toFixed(2)}%">${hourOf(t0) + h}時</span>`);
    const rows = c.pcs.map(pc => `<div class="tl-row"><span class="bar-label">${PCN(pc)}</span><div class="tl">${
      segs.filter(s => s.pc === pc).map(s => `<i style="${pos(s.t, s.d)};background:${HEX(s.c)}" title="${esc(D.colors[s.c].name)} ${hms(s.t)}〜${hms(s.t + s.d)} (${fmtDur(s.d)})"></i>`).join('')}${
      hides.filter(h => h.pc === pc).map(h => `<b style="${pos(h.t, h.e - h.t)}" title="見えていない ${hms(h.t)}〜${hms(h.e)} (${fmtDur(h.e - h.t)})"></b>`).join('')}</div></div>`).join('');
    return `<details ${i === 0 ? 'open' : ''}><summary>${dayStr(d)}</summary><div class="tl-wrap">
      <div class="tl-row"><span class="bar-label"></span><div class="tl-axis">${ticks.join('')}</div></div>${rows}</div></details>`;
  }).join('');
  const more = c.days.length > maxDays ? `（選択期間のうち新しい${maxDays}日分）` : '';
  return `<section><h2>タイムライン</h2><p class="note">各PCの状態の移り変わり${more}。帯にマウスを乗せると時刻が出ます。空白はログがない時間（監視停止中）、斜線は他のウィンドウが重なるなどで見えていなかった時間。</p>
    <div class="legend">${D.colors.map((_, i) => chip(i)).join('')}${HIDCHIP}</div>${blocks}</section>`;
}

// ------------------------------------------------------------ 描画と絞り込み
function render() {
  const c = compute();
  $('#from').value = dayISO(st.from); $('#to').value = dayISO(st.to);
  $('#range').textContent = `${c.days.length}日分・PC ${c.pcs.length}台`;
  document.querySelectorAll('#pcbtns button').forEach(b => b.classList.toggle('on', st.pcs.has(+b.dataset.pc)));
  if (!c.segs.length) { $('#main').innerHTML = '<section><p class="empty">選択した期間・PCのデータがありません。</p></section>'; return; }
  const parts = [kpis(c), insights(c)];
  if (DONE >= 0) parts.push(pcTable(c), daily(c), waits(c)); else parts.push(noRoles(), daily(c));
  parts.push(hourly(c), colorSummary(c), pcShare(c), detailMatrix(c), timeline(c));
  $('#main').innerHTML = parts.join('');
}

function init() {
  $('#sub').textContent = `ログ: ${D.logDir} ／ 作成: ${D.generated}`;
  if (!DAYS.length) { $('#main').innerHTML = '<section><p class="empty">ログがありません。</p></section>'; document.querySelector('.filters').style.display = 'none'; return; }
  for (const id of ['from', 'to']) { $('#' + id).min = dayISO(DAYS[0]); $('#' + id).max = dayISO(DAYS[DAYS.length - 1]); }
  $('#pcbtns').innerHTML = D.pcs.map((p, i) => `<button data-pc="${i}">${esc(p)}</button> `).join('');
  $('#pcbtns').addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return;
    const i = +b.dataset.pc; st.pcs.has(i) ? st.pcs.delete(i) : st.pcs.add(i); render(); });
  $('#pcall').onclick = () => { st.pcs = new Set(D.pcs.map((_, i) => i)); render(); };
  $('#pcnone').onclick = () => { st.pcs = new Set(); render(); };
  const last = DAYS[DAYS.length - 1];
  document.querySelectorAll('[data-q]').forEach(b => b.onclick = () => {
    const q = b.dataset.q; st.to = last;
    st.from = q === 'all' ? DAYS[0] : q === 'last' ? last : Math.max(DAYS[0], last - (+q - 1)); render(); });
  const onDate = () => { const f = $('#from').valueAsNumber, t = $('#to').valueAsNumber;
    if (!isNaN(f)) st.from = Math.floor(f / 864e5); if (!isNaN(t)) st.to = Math.floor(t / 864e5);
    if (st.from > st.to) [st.from, st.to] = [st.to, st.from]; render(); };
  $('#from').onchange = onDate; $('#to').onchange = onDate;
  render();
}
init();
</script>
</body></html>
"""


if __name__ == "__main__":
    main()
