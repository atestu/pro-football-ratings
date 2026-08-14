#!/usr/bin/env python3
"""Build the static site for profootballratings.com from committed data JSON.

Usage: python3 scripts/build_site.py [--out _site]
Pure stdlib. Reads data/scores/, writes index.html and copies site/fonts/.
"""
import argparse, json, html, pathlib, shutil

REPO = pathlib.Path(__file__).resolve().parents[1]
cli = argparse.ArgumentParser()
cli.add_argument("--out", default="_site")
OUT = REPO / cli.parse_args().out

ratings = json.load(open(REPO / "data/scores/ratings.json"))
lb = {int(p.parent.name): json.load(open(p))
      for p in sorted((REPO / "data/scores").glob("*/leaderboard.json"))}

experts = sorted(ratings["experts"], key=lambda e: -e["score"])
qualified = [e for e in experts if e["qualified"]]
incomplete = [e for e in experts if not e["qualified"]]

n_q = len(qualified)
n_bad = sum(1 for e in qualified if e["grade"].startswith(("D", "F")))
GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "D+", "D", "D-", "F"]
dist = [sum(1 for e in qualified if e["grade"] == g) for g in GRADES]
median_grade = sorted((e["grade"] for e in qualified), key=GRADES.index)[n_q // 2]
gen_date = ratings["generated_at"][:10]
seasons = ratings["parameters"]["seasons"]
term = f"{seasons[0]}–{seasons[-1]}"
total_picks = sum(e["total_picks"] for e in experts)

def esc(s): return html.escape(str(s), quote=True)

def enrolled(e):
    ys = e["seasons_active"]
    return str(ys[0]) if len(ys) == 1 else f"{ys[0]}–{str(ys[-1])[2:]}"

def chip(grade):
    return f'<span class="chip g{grade[0]}">{grade}</span>'

def vs_vegas_td(e):
    d = (e["accuracy"] - e["baseline_accuracy"]) * 100
    cls = "neg" if d < 0 else "pos"
    sign = "+" if d >= 0 else "−"
    return f'<td class="num {cls}" data-v="{d:.3f}">{sign}{abs(d):.1f}</td>'

# ---------- curve ----------
W, H = 680, 240
ML, MR, MT, MB = 36, 16, 26, 40
iw, ih = W - ML - MR, H - MT - MB
ymax = 18
def xpos(i): return ML + iw * (i + 0.5) / len(GRADES)
def ypos(c): return MT + ih * (1 - c / ymax)
pts = [(xpos(i), ypos(c)) for i, c in enumerate(dist)]

def smooth_path(p, close=False):
    d = [f"M{p[0][0]:.1f},{p[0][1]:.1f}"]
    for i in range(len(p) - 1):
        p0 = p[max(i - 1, 0)]; p1 = p[i]; p2 = p[i + 1]; p3 = p[min(i + 2, len(p) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        d.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    if close:
        d.append(f"L{p[-1][0]:.1f},{H-MB} L{p[0][0]:.1f},{H-MB} Z")
    return " ".join(d)

grid = "".join(f'<line class="gl" x1="{ML}" y1="{ypos(v):.1f}" x2="{W-MR}" y2="{ypos(v):.1f}"/>'
               f'<text class="yl" x="{ML-8}" y="{ypos(v)+3:.1f}">{v}</text>'
               for v in (5, 10, 15))
axis_labels = "".join(
    f'<text class="xl" x="{xpos(i):.1f}" y="{H-MB+18}">{g}</text>'
    for i, g in enumerate(GRADES))
counts = "".join(
    f'<text class="cl" x="{x:.1f}" y="{y-9:.1f}">{c}</text>'
    for (x, y), c in zip(pts, dist) if c)
dots = "".join(f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="3.2"/>' for x, y in pts)
hits = "".join(
    f'<div class="bin-hit" style="left:{(ML + iw*i/len(GRADES))/W*100:.2f}%; width:{iw/len(GRADES)/W*100:.2f}%" tabindex="0">'
    f'<span class="bin-tip">{g}: {c} of {n_q} rated pickers</span></div>'
    for i, (g, c) in enumerate(zip(GRADES, dist)))
curve_svg = f'''<div class="chart" role="img" aria-label="Grade distribution: {", ".join(f"{g} {c}" for g,c in zip(GRADES, dist))}">
  <svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">
    {grid}
    <line class="ax" x1="{ML}" y1="{H-MB}" x2="{W-MR}" y2="{H-MB}"/>
    <path class="area" d="{smooth_path(pts, close=True)}"/>
    <path class="curvepath" d="{smooth_path(pts)}"/>
    {dots}{counts}{axis_labels}
  </svg>
  {hits}
</div>'''

# ---------- ratings table ----------
rows = []
for i, e in enumerate(qualified, 1):
    rows.append(
        f'<tr><td class="num rk" data-v="{i}">{i}</td>'
        f'<td class="nm">{esc(e["expert_name"])}</td>'
        f'<td class="ol">{esc(e["outlet"])}</td>'
        f'<td class="num">{enrolled(e)}</td>'
        f'<td class="num" data-v="{e["total_picks"]}">{e["total_picks"]}</td>'
        f'<td class="num" data-v="{e["accuracy"]}">{e["accuracy"]*100:.1f}</td>'
        f'{vs_vegas_td(e)}'
        f'<td data-v="{-GRADES.index(e["grade"])}">{chip(e["grade"])}</td></tr>')
rank_rows = "\n".join(rows)
inc_names = ", ".join(f'{esc(e["expert_name"])} ({esc(e["outlet"])})' for e in incomplete)

by_slug = {e["expert"]: e for e in experts}
def notable(slug, text):
    e = by_slug[slug]
    d = (e["accuracy"] - e["baseline_accuracy"]) * 100
    sign = "+" if d >= 0 else "−"
    return f'''<article class="card">
  <header><h3>{esc(e["expert_name"])}</h3>{chip(e["grade"])}</header>
  <p class="card-meta">{esc(e["outlet"])} · {e["total_picks"]} picks · {e["accuracy"]*100:.1f}% · {sign}{abs(d):.1f} vs Vegas</p>
  <p>{text}</p>
</article>'''

notables = "\n".join([
    notable("fanduel",
            "The highest-rated picker on the board is a sportsbook. Five seasons of data, and the only picker who beats the favorite baseline by a wide margin. The best predictor of NFL games is the entity that sets the prices on them."),
    notable("chris-simms",
            "One season on file, but a real one: 268 picks at 66.8% against a 65.3% baseline. One of very few humans who beats the strategy that requires no thought."),
    notable("dan-graziano",
            "Ten seasons of professional picks, 6.2 points behind the no-thought baseline — the lowest rating on the board. Grading on a curve would not help; Dan is the curve."),
    notable("seth-wickersham",
            "On the board all eleven seasons. The feature writing is award-winning. The picks run 6.4 points behind a strategy summarized in full as: take the favorite."),
])

# ---------- season grids ----------
def season_grid(season, hidden):
    data = lb[season]
    exps = sorted(data["experts"], key=lambda e: -e["accuracy"])
    weeks = sorted({w["week"] for e in exps for w in e["weekly"]})
    best = {wk: max((w["correct"] for e in exps for w in e["weekly"] if w["week"] == wk), default=0)
            for wk in weeks}
    head = "".join(f'<th class="num">W{w}</th>' for w in weeks)
    body = []
    for e in exps:
        wk_map = {w["week"]: w for w in e["weekly"]}
        unq = e.get("qualified", True) is False
        cells = []
        for wk in weeks:
            w = wk_map.get(wk)
            if not w:
                cells.append('<td class="num empty">–</td>')
            else:
                pct = w["correct"] / w["total"] if w["total"] else 0
                h = min(5, max(0, int((pct - .35) / .10))) if pct >= .45 else 0
                cls = f"num h{h}" + (" best" if w["correct"] == best[wk] else "")
                cells.append(f'<td class="{cls}" title="{pct*100:.0f}% correct">'
                             f'{w["correct"]}/{w["total"]}</td>')
        name = esc(e["expert_name"]) + (' <span class="inc">not rated</span>' if unq else "")
        body.append(f'<tr{" class=unq" if unq else ""}><th scope="row" title="{esc(e["outlet"])}">{name}</th>'
                    + "".join(cells)
                    + f'<td class="num tot">{e["correct"]}/{e["total"]}</td>'
                    + f'<td class="num tot">{e["accuracy"]*100:.0f}%</td></tr>')
    return f'''<div class="yeargrid" id="year-{season}"{"" if not hidden else " hidden"}>
    <p class="sub">{len(exps)} pickers on file, through week {data["through_week"]}.</p>
    <div class="scroll tablecard">
      <table class="grid">
        <thead><tr><th>Picker</th>{head}<th class="num">Total</th><th class="num">Win%</th></tr></thead>
        <tbody>
{chr(10).join(body)}
        </tbody>
      </table>
    </div>
  </div>'''

years = sorted(lb, reverse=True)
year_btns = "".join(
    f'<button class="yearbtn" data-year="{y}" aria-pressed="{"true" if y == years[0] else "false"}">{y}</button>'
    for y in years)
year_grids = "\n".join(season_grid(y, hidden=(y != years[0])) for y in years)
seasons_panel = f'''<section class="panel" id="seasons" hidden>
  <div class="wrap">
    <h1>Seasons</h1>
    <p class="lead">Week-by-week results for every tracked picker: correct picks / games
    graded, shaded by weekly win rate. Straight-up picks only. Coverage before 2021 is
    thin — those seasons were recovered from web archives and hold only a handful of
    pickers.</p>
    <div class="years" role="group" aria-label="Pick a season">{year_btns}</div>
    <div class="heatkey"><span class="lbl">Weekly win rate</span>
      <i class="h1"></i><i class="h2"></i><i class="h3"></i><i class="h4"></i><i class="h5"></i>
      <span class="lbl">45% → 85%+</span>
      <i class="bestkey"></i><span class="lbl">best score of the week</span></div>
    {year_grids}
  </div>
</section>'''

FONTS = [("Barlow Condensed", "600", "barlow-condensed-600.woff2"),
         ("Barlow Condensed", "700", "barlow-condensed-700.woff2"),
         ("IBM Plex Sans", "400", "ibm-plex-sans-400.woff2"),
         ("IBM Plex Sans", "600", "ibm-plex-sans-600.woff2"),
         ("IBM Plex Mono", "400 600", "ibm-plex-mono.woff2")]
fontfaces = "\n".join(
    f"@font-face {{ font-family:'{fam}'; font-style:normal; font-weight:{wt}; "
    f"font-display:swap; src:url(fonts/{fn}) format('woff2'); }}"
    for fam, wt, fn in FONTS)

page = f'''<title>Pro Football Ratings</title>
<style>
{fontfaces}

:root {{
  --bg:#FCFCFA; --surface:#FFFFFF; --band:#F4F5F1; --ink:#1A2430; --muted:#5B6570;
  --line:#E2E4DF; --accent:#D9530B; --accent-deep:#A63F06; --accent-soft:rgba(217,83,11,.12);
  --pos:#0A6B5A; --neg:#A8352F; --heat:217,83,11;
  --gA-bg:#D3E8DF; --gA-fg:#084C3F; --gB-bg:#E4F0E9; --gB-fg:#2E6B54;
  --gC-bg:#E8EAEC; --gC-fg:#454F59; --gD-bg:#F6DFD8; --gD-fg:#8A3A2C;
  --gF-bg:#F2CFCC; --gF-fg:#7E1F2D;
  --tip-bg:#1A2430; --tip-fg:#FFFFFF;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#14181D; --surface:#1B2127; --band:#181E24; --ink:#E8EAED; --muted:#9AA3AC;
    --line:#2A3138; --accent:#F0782E; --accent-deep:#F0985E; --accent-soft:rgba(240,120,46,.16);
    --pos:#5FC2A8; --neg:#E58B82; --heat:240,120,46;
    --gA-bg:#123A31; --gA-fg:#8FD6BE; --gB-bg:#17332B; --gB-fg:#9CC9B4;
    --gC-bg:#272E36; --gC-fg:#AEB7BF; --gD-bg:#3E211B; --gD-fg:#E5A08F;
    --gF-bg:#44191E; --gF-fg:#EE9DA1;
    --tip-bg:#E8EAED; --tip-fg:#14181D;
  }}
}}
:root[data-theme="dark"] {{
  --bg:#14181D; --surface:#1B2127; --band:#181E24; --ink:#E8EAED; --muted:#9AA3AC;
  --line:#2A3138; --accent:#F0782E; --accent-deep:#F0985E; --accent-soft:rgba(240,120,46,.16);
  --pos:#5FC2A8; --neg:#E58B82; --heat:240,120,46;
  --gA-bg:#123A31; --gA-fg:#8FD6BE; --gB-bg:#17332B; --gB-fg:#9CC9B4;
  --gC-bg:#272E36; --gC-fg:#AEB7BF; --gD-bg:#3E211B; --gD-fg:#E5A08F;
  --gF-bg:#44191E; --gF-fg:#EE9DA1;
  --tip-bg:#E8EAED; --tip-fg:#14181D;
}}

* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:400 15px/1.6 'IBM Plex Sans', system-ui, sans-serif; }}
a {{ color:var(--accent-deep); }}
a:focus-visible, button:focus-visible, .bin-hit:focus-visible {{
  outline:2px solid var(--accent); outline-offset:2px; }}
.wrap {{ max-width:1040px; margin:0 auto; padding:0 20px; }}

/* nav */
.topbar {{ border-bottom:1px solid var(--line); background:var(--surface); }}
.topbar .wrap {{ display:flex; align-items:center; gap:28px; min-height:58px; flex-wrap:wrap; }}
.logo {{ font:700 24px/1 'Barlow Condensed', sans-serif; letter-spacing:.03em;
  text-transform:uppercase; color:var(--ink); text-decoration:none; }}
.logo b {{ color:var(--accent); font-weight:700; }}
nav {{ display:flex; gap:4px; margin-left:auto; }}
nav button {{ font:600 15px/1 'Barlow Condensed', sans-serif; letter-spacing:.08em;
  text-transform:uppercase; color:var(--muted); background:none; border:none;
  padding:20px 12px 17px; border-bottom:3px solid transparent; cursor:pointer; }}
nav button[aria-current="true"] {{ color:var(--ink); border-bottom-color:var(--accent); }}
nav button:hover {{ color:var(--ink); }}

/* hero */
.hero {{ background:var(--band); border-bottom:1px solid var(--line); padding:44px 0 36px; }}
.hero h1 {{ font:700 clamp(34px,5vw,52px)/1.02 'Barlow Condensed', sans-serif;
  text-transform:uppercase; letter-spacing:.01em; margin:0 0 12px; text-wrap:balance; }}
.hero .dek {{ max-width:62ch; margin:0 0 26px; font-size:16px; color:var(--ink); }}
.stats {{ display:flex; gap:36px; flex-wrap:wrap; }}
.stat .v {{ font:600 30px/1.1 'IBM Plex Mono', monospace; display:block; }}
.stat .v .chip {{ font-size:20px; vertical-align:6px; }}
.stat .l {{ font:600 11px/1.4 'IBM Plex Sans', sans-serif; letter-spacing:.14em;
  text-transform:uppercase; color:var(--muted); }}

.panel .wrap > h1 {{ font:700 clamp(28px,4vw,40px)/1.05 'Barlow Condensed', sans-serif;
  text-transform:uppercase; margin:36px 0 10px; }}
.lead {{ color:var(--muted); max-width:70ch; margin:0 0 20px; }}
h2 {{ font:600 22px/1.2 'Barlow Condensed', sans-serif; text-transform:uppercase;
  letter-spacing:.05em; margin:44px 0 6px; }}
.sub {{ color:var(--muted); font-size:13.5px; margin:0 0 16px; max-width:70ch; }}

/* chips */
.chip {{ display:inline-block; font:600 12.5px/1 'IBM Plex Mono', monospace;
  padding:4px 8px 3px; border-radius:4px; min-width:30px; text-align:center; }}
.gA {{ background:var(--gA-bg); color:var(--gA-fg); }}
.gB {{ background:var(--gB-bg); color:var(--gB-fg); }}
.gC {{ background:var(--gC-bg); color:var(--gC-fg); }}
.gD {{ background:var(--gD-bg); color:var(--gD-fg); }}
.gF {{ background:var(--gF-bg); color:var(--gF-fg); }}

/* tables */
.tablecard {{ background:var(--surface); border:1px solid var(--line); border-radius:6px; }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ padding:8px 12px; text-align:left; white-space:nowrap; font-size:13.5px; }}
thead th {{ font:600 11px/1.3 'IBM Plex Sans', sans-serif; letter-spacing:.12em;
  text-transform:uppercase; color:var(--muted); border-bottom:2px solid var(--line);
  position:sticky; top:0; background:var(--surface); }}
tbody td, tbody th {{ border-bottom:1px solid var(--line); }}
tbody tr:last-child td, tbody tr:last-child th {{ border-bottom:none; }}
tbody tr:hover td, tbody tr:hover th {{ background:var(--band); }}
.num {{ font-family:'IBM Plex Mono', monospace; font-variant-numeric:tabular-nums;
  text-align:right; }}
td.rk {{ color:var(--muted); }}
td.nm {{ font-weight:600; }}
td.ol {{ color:var(--muted); font-size:12.5px; }}
td.pos {{ color:var(--pos); }}
td.neg {{ color:var(--neg); }}
table.rank thead th {{ cursor:pointer; user-select:none; }}
table.rank thead th.sorted {{ color:var(--ink); }}
table.rank thead th.sorted::after {{ content:' ▾'; color:var(--accent); }}
table.rank thead th.sorted.asc::after {{ content:' ▴'; }}
.tablenote {{ color:var(--muted); font-size:12.5px; padding:10px 12px;
  border-top:1px solid var(--line); margin:0; }}

/* season grid */
table.grid thead th, table.grid td, table.grid tbody th {{ padding:6px 9px; font-size:12.5px; }}
table.grid tbody th {{ font-weight:600; text-align:left; position:sticky; left:0;
  background:var(--surface); z-index:1; }}
table.grid tbody tr:hover th {{ background:var(--band); }}
table.grid td.best {{ box-shadow:inset 0 0 0 2px var(--accent-deep); font-weight:600; }}
table.grid td.empty {{ color:var(--muted); }}
.h1 {{ background:rgba(var(--heat), .09); }}
.h2 {{ background:rgba(var(--heat), .18); }}
.h3 {{ background:rgba(var(--heat), .28); }}
.h4 {{ background:rgba(var(--heat), .40); }}
.h5 {{ background:rgba(var(--heat), .54); }}
.heatkey {{ display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin:0 0 16px; }}
.heatkey i {{ width:24px; height:14px; border-radius:3px; border:1px solid var(--line);
  background:var(--surface); }}
.heatkey i.bestkey {{ box-shadow:inset 0 0 0 2px var(--accent-deep); margin-left:14px; }}
.heatkey .lbl {{ font-size:12px; color:var(--muted); margin:0 5px; }}
table.grid tr.unq {{ color:var(--muted); }}
table.grid .inc {{ font-size:10px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted); }}
table.grid td.tot {{ font-weight:600; }}
mark.key {{ background:var(--accent-soft); padding:0 8px; border-radius:3px; }}
.years {{ display:flex; gap:6px; flex-wrap:wrap; margin:0 0 18px; }}
.yearbtn {{ font:600 14px/1 'IBM Plex Mono', monospace; color:var(--muted);
  background:var(--surface); border:1px solid var(--line); border-radius:4px;
  padding:8px 12px; cursor:pointer; }}
.yearbtn[aria-pressed="true"] {{ color:var(--ink); border-color:var(--accent);
  box-shadow:inset 0 -3px 0 var(--accent); }}
.yearbtn:hover {{ color:var(--ink); }}

/* chart */
.chart {{ position:relative; background:var(--surface); border:1px solid var(--line);
  border-radius:6px; padding:14px 10px 6px; max-width:760px; }}
.chart svg {{ display:block; width:100%; height:auto; }}
.gl {{ stroke:var(--line); stroke-width:1; }}
.ax {{ stroke:var(--muted); stroke-width:1.2; }}
.yl {{ font:10.5px 'IBM Plex Mono', monospace; fill:var(--muted); text-anchor:end; }}
.xl {{ font:600 11.5px 'IBM Plex Mono', monospace; fill:var(--ink); text-anchor:middle; }}
.cl {{ font:600 11px 'IBM Plex Mono', monospace; fill:var(--accent-deep); text-anchor:middle; }}
.curvepath {{ fill:none; stroke:var(--accent); stroke-width:2.2; stroke-linecap:round;
  stroke-dasharray:1400; stroke-dashoffset:1400; animation:draw 1s ease-out .3s forwards; }}
@keyframes draw {{ to {{ stroke-dashoffset:0; }} }}
.area {{ fill:var(--accent-soft); stroke:none; }}
.dot {{ fill:var(--accent); }}
.bin-hit {{ position:absolute; top:0; bottom:0; }}
.bin-hit .bin-tip {{ display:none; position:absolute; top:10px; left:50%; transform:translateX(-50%);
  background:var(--tip-bg); color:var(--tip-fg); border-radius:4px; padding:4px 9px;
  font-size:12px; white-space:nowrap; z-index:2; }}
.bin-hit:hover .bin-tip, .bin-hit:focus-visible .bin-tip {{ display:block; }}

/* notables */
.cards {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:16px; }}
.card {{ background:var(--surface); border:1px solid var(--line); border-radius:6px;
  padding:16px 18px; }}
.card header {{ display:flex; align-items:center; justify-content:space-between; gap:10px; }}
.card h3 {{ font:600 19px/1.2 'Barlow Condensed', sans-serif; text-transform:uppercase;
  letter-spacing:.04em; margin:0; }}
.card-meta {{ color:var(--muted); font-size:12px; font-family:'IBM Plex Mono', monospace;
  margin:4px 0 8px; }}
.card p {{ margin:0; font-size:13.5px; }}

details {{ margin:18px 0 0; }}
summary {{ cursor:pointer; color:var(--accent-deep); font-weight:600; font-size:13.5px; }}
details p {{ color:var(--muted); font-size:13px; max-width:80ch; }}

/* methodology */
.steps {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:16px;
  margin:20px 0 8px; }}
.step {{ background:var(--surface); border:1px solid var(--line); border-radius:6px;
  padding:16px 18px; }}
.step h3 {{ font:600 16px/1 'Barlow Condensed', sans-serif; letter-spacing:.1em;
  text-transform:uppercase; margin:0 0 8px; }}
.step h3 span {{ color:var(--accent); margin-right:6px; }}
.step p {{ margin:0; font-size:13.5px; color:var(--ink); }}
.legend {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:14px 0; }}
.legend .lbl {{ font-size:12.5px; color:var(--muted); }}

.sitefooter {{ border-top:1px solid var(--line); margin-top:56px; padding:22px 0 40px;
  color:var(--muted); font-size:12.5px; }}
.sitefooter .wrap {{ display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
.panel {{ padding-bottom:8px; }}

@media (max-width:720px) {{
  .topbar .wrap {{ gap:10px; }}
  nav {{ margin-left:0; overflow-x:auto; width:100%; }}
  nav button {{ padding:12px 10px; }}
  .stats {{ gap:22px; }}
}}
@media (prefers-reduced-motion:reduce) {{
  .curvepath {{ animation:none; stroke-dashoffset:0; }}
}}
</style>

<header class="topbar">
  <div class="wrap">
    <a class="logo" href="#ratings">Pro Football <b>Ratings</b></a>
    <nav aria-label="Site">
      <button aria-current="true" data-panel="ratings">Ratings</button>
      <button aria-current="false" data-panel="seasons">Seasons</button>
      <button aria-current="false" data-panel="methodology">Methodology</button>
    </nav>
  </div>
</header>

<section class="panel" id="ratings">
  <div class="hero">
    <div class="wrap">
      <h1>Who actually beats Vegas?</h1>
      <p class="dek">Media experts pick every NFL game, every week, in public — and nobody
      checks their work. We do. Every published pick from ESPN, NFL.com, ProFootballTalk,
      and Fantasy Nerds is recorded before kickoff, scored against the final result, and
      rated against the simplest baseline in football: always take the favorite.
      Most experts lose to it.</p>
      <div class="stats">
        <div class="stat"><span class="v">{len(experts)}</span><span class="l">Pickers tracked</span></div>
        <div class="stat"><span class="v">{total_picks:,}</span><span class="l">Picks graded</span></div>
        <div class="stat"><span class="v">{term}</span><span class="l">Seasons covered</span></div>
        <div class="stat"><span class="v">{chip(median_grade)}</span><span class="l">Median grade</span></div>
      </div>
    </div>
  </div>

  <div class="wrap">
    <h2>Ratings</h2>
    <p class="sub">All {n_q} pickers with 100+ recorded picks, ranked by rating —
    recency-weighted performance against the take-the-favorite baseline. A grade of C
    means matching Vegas; {n_bad} of {n_q} rate D or worse. Click a column to sort.</p>
    <div class="scroll tablecard">
      <table class="rank" id="ranktable">
        <thead><tr>
          <th class="num" data-sort="num">#</th><th data-sort="text">Picker</th>
          <th data-sort="text">Outlet</th><th class="num">Seasons</th>
          <th class="num" data-sort="num">Picks</th><th class="num" data-sort="num">Win%</th>
          <th class="num" data-sort="num">vs Vegas</th><th data-sort="num">Grade</th>
        </tr></thead>
        <tbody>
{rank_rows}
        </tbody>
      </table>
      <p class="tablenote">The two highest-rated pickers are sportsbooks. Make of that
      what you will.</p>
    </div>
    <details>
      <summary>{len(incomplete)} more pickers tracked without enough picks to rate</summary>
      <p>Under 100 recorded picks; tracked but unrated: {inc_names}.</p>
    </details>

    <h2>Graded on a curve</h2>
    <p class="sub">Distribution of the {n_q} rated pickers. The shelf on the left is
    everyone beating or matching Vegas; the spike on the right is everyone else.</p>
    {curve_svg}

    <h2>Notable</h2>
    <div class="cards">
{notables}
    </div>
  </div>
</section>

{seasons_panel}

<section class="panel" id="methodology" hidden>
  <div class="wrap">
    <h1>Methodology</h1>
    <p class="lead">Everything on this site is generated from public data on a weekly
    cycle. Picks are recorded before games are played and never edited after the fact.</p>
    <div class="steps">
      <div class="step"><h3><span>1</span>Collect</h3><p>Thursday at noon ET, every
        published pick from ESPN, NFL.com, ProFootballTalk, and Fantasy Nerds is recorded
        — hours before the first kickoff.</p></div>
      <div class="step"><h3><span>2</span>Score</h3><p>Tuesday morning, after Monday
        Night Football, final results arrive from nflverse and every pick on file is
        marked correct or incorrect.</p></div>
      <div class="step"><h3><span>3</span>Rate</h3><p>Each picker's record is measured
        against picking the Vegas favorite in the same games, weighted toward recent
        seasons (52-week half-life). The weighted score maps to a letter grade.</p></div>
    </div>
    <h2>The grading scale</h2>
    <div class="legend">
      {chip("A+")}{chip("B")}{chip("C")}{chip("D")}{chip("F")}
      <span class="lbl">C = matches Vegas exactly. Above C beats the market;
      below C loses to a rule a child could follow.</span>
    </div>
    <p class="sub">100 picks minimum to be rated. Straight-up picks only — against-the-spread
    ratings are planned. Also planned: submit your own picks and get rated on the same
    scale as the professionals.</p>
  </div>
</section>

<footer class="sitefooter">
  <div class="wrap">
    <span>profootballratings.com — updated automatically; last build {gen_date}.
      Not affiliated with the NFL or any outlet. Not betting advice.</span>
    <span>Game data from <a href="https://github.com/nflverse">nflverse</a> ·
      <a href="https://github.com/atestu/pro-football-ratings">built in the open</a></span>
  </div>
</footer>

<script>
const navBtns = [...document.querySelectorAll('nav button')];
const panels = [...document.querySelectorAll('.panel')];
function show(id) {{
  panels.forEach(p => p.hidden = p.id !== id);
  navBtns.forEach(b => b.setAttribute('aria-current', String(b.dataset.panel === id)));
}}
navBtns.forEach(b => b.addEventListener('click', () => {{
  show(b.dataset.panel);
  history.replaceState(null, '', '#' + b.dataset.panel);
  window.scrollTo(0, 0);
}}));
if (panels.some(p => p.id === location.hash.slice(1))) show(location.hash.slice(1));

// season year picker
const yearBtns = [...document.querySelectorAll('.yearbtn')];
const yearGrids = [...document.querySelectorAll('.yeargrid')];
yearBtns.forEach(b => b.addEventListener('click', () => {{
  yearGrids.forEach(g => g.hidden = g.id !== 'year-' + b.dataset.year);
  yearBtns.forEach(x => x.setAttribute('aria-pressed', String(x === b)));
}}));

// sortable ratings table
const table = document.getElementById('ranktable');
const heads = [...table.querySelectorAll('thead th')];
heads.forEach((th, col) => {{
  if (!th.dataset.sort) return;
  th.addEventListener('click', () => {{
    const asc = th.classList.contains('sorted') && !th.classList.contains('asc');
    heads.forEach(h => h.classList.remove('sorted', 'asc'));
    th.classList.add('sorted'); if (asc) th.classList.add('asc');
    const body = table.tBodies[0];
    const rows = [...body.rows];
    const key = r => {{
      const c = r.cells[col];
      return th.dataset.sort === 'num' ? parseFloat(c.dataset.v ?? c.textContent) : c.textContent.trim();
    }};
    rows.sort((a, b) => {{
      const x = key(a), y = key(b);
      const cmp = typeof x === 'number' ? y - x : String(x).localeCompare(String(y));
      return asc ? -cmp : cmp;
    }});
    rows.forEach(r => body.appendChild(r));
  }});
}});
</script>
'''

FAVICON = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' "
           "viewBox='0 0 100 100'><text y='.9em' font-size='90'>%F0%9F%8F%88</text></svg>")
head, body_html = page.split("</style>", 1)
doc = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
       "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
       "<meta name=\"description\" content=\"Every published NFL expert pick, recorded "
       "before kickoff and rated against a Vegas baseline.\">\n"
       f"<link rel=\"icon\" href=\"{FAVICON}\">\n"
       + head + "</style>\n</head>\n<body>\n" + body_html + "\n</body>\n</html>\n")
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "index.html").write_text(doc)
shutil.copytree(REPO / "site/fonts", OUT / "fonts", dirs_exist_ok=True)
print(f"wrote {OUT / 'index.html'} ({(OUT / 'index.html').stat().st_size / 1024:.0f}KB) + fonts")
