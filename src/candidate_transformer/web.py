"""Minimal web UI for the candidate transformer.

Run it with::

    python -m candidate_transformer.web        # then open http://127.0.0.1:5000

The UI is intentionally thin. It lets you pick which of the bundled sample
sources to ingest and which output config to apply, then renders every merged
profile with its overall confidence, per-skill confidence, and the full
provenance trail. The work happens in :mod:`candidate_transformer.pipeline`;
this module only collects form input and renders results. Flask is an optional
dependency (``pip install -e ".[web]"``); the CLI works without it.
"""
from __future__ import annotations

import glob
import json
import os
import tempfile
from typing import Dict, List, Optional

from .config import OutputConfig
from .pipeline import SourceSpec, run
from .scoring import blend_score, keyword_match, parse_keywords

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_PKG_DIR))  # repo root (src-layout)
SAMPLES_DIR = os.path.join(_ROOT, "samples", "inputs")
CONFIGS_DIR = os.path.join(_ROOT, "configs")


def _list_samples() -> List[str]:
    if not os.path.isdir(SAMPLES_DIR):
        return []
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(SAMPLES_DIR, "*"))
                  if os.path.isfile(p))


def _list_configs() -> List[str]:
    if not os.path.isdir(CONFIGS_DIR):
        return []
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(CONFIGS_DIR, "*.json")))


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Candidate Data Transformer</title>
<style>
  :root{
    --bg:#f4f5f9; --surface:#ffffff; --ink:#0f172a; --body:#334155; --muted:#64748b;
    --line:#e6e8f0; --line2:#eef0f6; --accent:#4f46e5; --accent-ink:#4338ca; --accent-weak:#eef2ff;
    --green:#15a34a; --amber:#d97706; --red:#dc2626;
    --shadow:0 1px 2px rgba(15,23,42,.04),0 2px 6px rgba(15,23,42,.06);
    --radius:14px;
  }
  *{box-sizing:border-box;}
  html,body{margin:0;}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg); color:var(--body); line-height:1.5; -webkit-font-smoothing:antialiased;}
  svg{stroke-linecap:round; stroke-linejoin:round;}

  .topbar{background:var(--surface); border-bottom:1px solid var(--line);}
  .topbar .inner{max-width:1040px; margin:0 auto; padding:16px 24px; display:flex; align-items:center; gap:14px;}
  .logo{width:38px; height:38px; border-radius:10px; flex:0 0 auto; color:#fff; font-weight:800; font-size:15px;
        letter-spacing:.5px; display:flex; align-items:center; justify-content:center; box-shadow:var(--shadow);
        background:linear-gradient(135deg,#6366f1,#4f46e5);}
  .topbar h1{margin:0; font-size:17px; color:var(--ink); font-weight:700; letter-spacing:-.01em;}
  .topbar p{margin:2px 0 0; font-size:13px; color:var(--muted);}

  main{max-width:1040px; margin:0 auto; padding:24px 24px 72px;}

  .panel{background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
         box-shadow:var(--shadow); padding:20px 22px;}
  .panel-title{font-size:12px; font-weight:700; color:var(--muted); text-transform:uppercase;
               letter-spacing:.07em; margin:0 0 16px;}

  .field{margin-bottom:18px;}
  .field .lbl{display:block; font-size:12px; font-weight:700; color:var(--muted); text-transform:uppercase;
              letter-spacing:.06em; margin-bottom:9px;}
  .chips{display:flex; flex-wrap:wrap; gap:9px;}
  .chip{position:relative; display:inline-flex; align-items:center; gap:8px; cursor:pointer; user-select:none;
        border:1px solid var(--line); background:#fff; border-radius:10px; padding:8px 13px; font-size:13px;
        color:var(--body); transition:border-color .12s, background .12s, color .12s;}
  .chip:hover{border-color:#c7cbe0; background:#fafbff;}
  .chip input{position:absolute; opacity:0; pointer-events:none;}
  .chip .dot{width:16px; height:16px; border-radius:5px; border:1.5px solid #c3c8de; flex:0 0 auto;
             display:flex; align-items:center; justify-content:center; transition:all .12s;}
  .chip .dot svg{width:11px; height:11px; stroke:#fff; stroke-width:3.5; fill:none; opacity:0;}
  .chip code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; color:inherit;}
  .chip input:checked ~ .dot{background:var(--accent); border-color:var(--accent);}
  .chip input:checked ~ .dot svg{opacity:1;}
  .chip:has(input:checked){border-color:var(--accent); background:var(--accent-weak); color:var(--accent-ink);}

  select{appearance:none; -webkit-appearance:none; font-size:14px; color:var(--ink); background-color:#fff;
         border:1px solid var(--line); border-radius:10px; padding:10px 38px 10px 13px; min-width:300px; max-width:100%;
         cursor:pointer; background-repeat:no-repeat; background-position:right 12px center;
         background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2364748b' stroke-width='2.2'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");}
  select:focus{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-weak);}

  .actions{display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-top:20px; padding-top:18px;
           border-top:1px solid var(--line2);}
  .btn{display:inline-flex; align-items:center; gap:8px; background:var(--accent); color:#fff; border:none;
       cursor:pointer; font-size:14px; font-weight:600; padding:11px 20px; border-radius:10px;
       box-shadow:var(--shadow); transition:background .12s;}
  .btn:hover{background:var(--accent-ink);}
  .btn svg{width:16px; height:16px; stroke:#fff; stroke-width:2; fill:none;}
  .hint{font-size:12.5px; color:var(--muted);}

  textarea{width:100%; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; color:var(--ink);
           background:#fff; border:1px solid var(--line); border-radius:10px; padding:10px 12px; resize:vertical; line-height:1.45;}
  textarea:focus{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-weak);}
  input.kwbox{width:100%; max-width:560px; font-size:14px; color:var(--ink); background:#fff;
              border:1px solid var(--line); border-radius:10px; padding:10px 13px;}
  input.kwbox:focus{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-weak);}

  .kwrow{display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin:14px 0 2px;}
  .kwrow .lead{font-size:11px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; margin-right:2px;}
  .kw{display:inline-flex; align-items:center; gap:5px; font-size:12px; font-weight:600; border-radius:999px; padding:3px 10px; border:1px solid;}
  .kw svg{width:11px; height:11px; stroke-width:3; fill:none;}
  .kw.hit{color:var(--accent-ink); background:var(--accent-weak); border-color:#dfe3fb;}
  .kw.hit svg{stroke:var(--accent);}
  .kw.miss{color:var(--muted); background:#f8fafc; border-color:var(--line); text-decoration:line-through; text-decoration-color:#cbd5e1;}
  .conf .base{font-weight:600; opacity:.8;}
  .prow{border:1px dashed var(--line); border-radius:12px; padding:12px; margin-bottom:10px; background:#fcfcfe;}
  .prow-top{display:flex; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap;}
  .prow select{min-width:210px;}
  .mini{font-size:12px; font-weight:600; color:var(--accent-ink); background:var(--accent-weak); border:1px solid #dfe3fb;
        border-radius:8px; padding:6px 11px; cursor:pointer;}
  .mini:hover{background:#e4e8ff;}
  .mini.del-btn{margin-left:auto; color:#b91c1c; background:#fef2f2; border-color:#fecaca; font-size:16px; line-height:1; padding:4px 11px;}
  .addrow{font-size:13px; font-weight:600; color:var(--accent-ink); background:none; border:1px dashed #c3c8de;
          border-radius:10px; padding:9px 14px; cursor:pointer; width:100%;}
  .addrow:hover{background:#fafbff; border-color:var(--accent);}

  .summary{display:flex; flex-wrap:wrap; gap:10px; margin:22px 0 4px;}
  .stat{display:inline-flex; align-items:center; gap:8px; background:var(--surface); border:1px solid var(--line);
        border-radius:10px; padding:9px 14px; font-size:13px; color:var(--body); box-shadow:var(--shadow);}
  .stat b{color:var(--ink); font-size:15px; font-weight:700;}
  .stat .swatch{width:8px; height:8px; border-radius:50%;}

  .warns{background:#fffbeb; border:1px solid #fde68a; color:#92400e; border-radius:12px; padding:14px 16px;
         font-size:13px; margin:16px 0; box-shadow:var(--shadow);}
  .warns .whead{display:flex; align-items:center; gap:8px; font-weight:700; margin-bottom:8px;}
  .warns .whead svg{width:16px; height:16px; stroke:#b45309; stroke-width:2; fill:none;}
  .warns ul{margin:0; padding-left:20px;} .warns li{margin:3px 0;}

  .card{background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
        box-shadow:var(--shadow); padding:22px 24px; margin-top:16px;}
  .chead{display:flex; align-items:flex-start; gap:14px;}
  .avatar{width:46px; height:46px; border-radius:12px; flex:0 0 auto; color:#fff; font-weight:700; font-size:16px;
          display:flex; align-items:center; justify-content:center; background:linear-gradient(135deg,#818cf8,#4f46e5);}
  .chead .who{flex:1 1 auto; min-width:0;}
  .chead h2{margin:0; font-size:18px; color:var(--ink); font-weight:700; letter-spacing:-.01em;}
  .chead .role{font-size:13.5px; color:var(--muted); margin-top:2px;}
  .chead .cid{font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11.5px; color:#94a3b8; margin-top:4px;}
  .conf{flex:0 0 auto; display:inline-flex; align-items:center; gap:7px; font-size:12.5px; font-weight:700;
        padding:6px 12px; border-radius:999px; color:#fff;}
  .conf .cdot{width:7px; height:7px; border-radius:50%; background:rgba(255,255,255,.85);}

  .divider{height:1px; background:var(--line2); margin:18px 0;}

  .contact{display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px 26px;}
  .ci{display:flex; align-items:center; gap:10px; font-size:13.5px; color:var(--body); min-width:0;}
  .ci svg{width:16px; height:16px; stroke:#94a3b8; stroke-width:2; fill:none; flex:0 0 auto;}
  .ci span{overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}

  .sec{font-size:11px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.07em;
       margin:18px 0 10px;}

  .pill{display:inline-flex; align-items:center; gap:9px; background:#fff; border:1px solid var(--line);
        border-radius:999px; padding:5px 12px 5px 13px; font-size:13px; color:var(--ink); margin:0 7px 8px 0;}
  .pill .bar{height:5px; width:46px; border-radius:3px; background:#edeff5; overflow:hidden;}
  .pill .bar > i{display:block; height:100%; background:linear-gradient(90deg,#818cf8,#4f46e5);}

  .tl{position:relative; padding-left:20px;}
  .tl::before{content:""; position:absolute; left:5px; top:4px; bottom:4px; width:2px; background:var(--line);}
  .tl .item{position:relative; margin:0 0 12px;}
  .tl .item:last-child{margin-bottom:0;}
  .tl .item::before{content:""; position:absolute; left:-19px; top:5px; width:10px; height:10px; border-radius:50%;
                    background:#fff; border:2.5px solid var(--accent);}
  .tl .t{font-size:14px; color:var(--ink); font-weight:600;}
  .tl .t .c{color:var(--body); font-weight:400;}
  .tl .when{font-size:12px; color:var(--muted); margin-top:1px; font-variant-numeric:tabular-nums;}

  .edu .item{margin:0 0 9px; font-size:13.5px; color:var(--body);}
  .edu .item:last-child{margin-bottom:0;}
  .edu .deg{color:var(--ink); font-weight:600;}

  details{margin-top:14px; border-top:1px solid var(--line2); padding-top:12px;}
  summary{cursor:pointer; font-size:13px; color:var(--accent-ink); font-weight:600; list-style:none;
          display:inline-flex; align-items:center; gap:6px;}
  summary::-webkit-details-marker{display:none;}
  summary::before{content:"\\25B8"; font-size:11px; transition:transform .12s;}
  details[open] summary::before{transform:rotate(90deg);}
  table{border-collapse:collapse; width:100%; font-size:12.5px; margin-top:12px;}
  th,td{text-align:left; padding:7px 10px; border-bottom:1px solid var(--line2);}
  thead th{color:var(--muted); font-weight:700; text-transform:uppercase; font-size:10.5px; letter-spacing:.05em; background:#fafbfd;}
  tbody tr:hover{background:#fafbff;}
  td .tag{font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px; background:var(--accent-weak);
          color:var(--accent-ink); padding:1px 7px; border-radius:6px;}
  pre{background:#0f172a; color:#e2e8f0; padding:16px; border-radius:10px; overflow:auto; font-size:12px; margin-top:12px;
      font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}
  .empty{color:var(--muted); font-style:italic;}

  @media (max-width:640px){
    .contact{grid-template-columns:1fr;}
    .topbar p{display:none;}
    select{min-width:100%; width:100%;}
  }
</style></head><body>
<div class="topbar"><div class="inner">
  <div class="logo">CT</div>
  <div>
    <h1>Multi-Source Candidate Data Transformer</h1>
    <p>Merge messy multi-source candidate data into canonical profiles &mdash; with provenance &amp; confidence.</p>
  </div>
</div></div>
<main>
  <form method="post" action="/run" class="panel">
    <div class="panel-title">Configure run</div>
    <div class="field">
      <span class="lbl">Sources</span>
      <div class="chips">
        {% for s in samples %}
        <label class="chip"><input type="checkbox" name="source" value="{{ s }}" {% if s in selected_sources %}checked{% endif %}>
          <span class="dot"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></span>
          <code>{{ s }}</code></label>
        {% endfor %}
      </div>
    </div>
    <div class="field">
      <span class="lbl">Or paste your own sources</span>
      <div id="pastes">
        {% for r in paste_rows %}
        <div class="prow">
          <div class="prow-top">
            <select name="paste_type" class="ptype">
              <option value="" {% if not r.type %}selected{% endif %}>Choose source type&hellip;</option>
              <option value="recruiter_csv" {% if r.type=='recruiter_csv' %}selected{% endif %}>Recruiter CSV</option>
              <option value="ats_json" {% if r.type=='ats_json' %}selected{% endif %}>ATS JSON</option>
              <option value="resume" {% if r.type=='resume' %}selected{% endif %}>R&eacute;sum&eacute; text</option>
              <option value="recruiter_notes" {% if r.type=='recruiter_notes' %}selected{% endif %}>Recruiter notes</option>
            </select>
            <button type="button" class="mini sample-btn">Load sample</button>
            <button type="button" class="mini del-btn" title="Remove this source">&times;</button>
          </div>
          <textarea name="paste_text" class="ptext" rows="4" placeholder="Paste CSV rows, an ATS JSON blob, resume text, or free-form notes...">{{ r.text }}</textarea>
        </div>
        {% endfor %}
      </div>
      <button type="button" class="addrow" id="addrow">+ Add another source</button>
    </div>
    <div class="field">
      <span class="lbl">Output config</span>
      <select name="config">
        <option value="" {% if not selected_config %}selected{% endif %}>Default &mdash; full canonical schema</option>
        {% for c in configs %}
        <option value="{{ c }}" {% if c == selected_config %}selected{% endif %}>{{ c }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="field">
      <span class="lbl">Priority keywords <span style="text-transform:none; font-weight:400; color:var(--muted)">(optional)</span></span>
      <input class="kwbox" type="text" name="keywords" value="{{ keywords_str }}"
             placeholder="e.g. kubernetes, go, fintech, react">
      <div class="hint" style="margin-top:7px">Leave blank to rank purely by our confidence score. Add terms to prefer
        candidates whose skills or background match &mdash; matched candidates rise to the top.</div>
    </div>
    <div class="actions">
      <button class="btn" type="submit">
        <svg viewBox="0 0 24 24"><path d="M12 2 2 7l10 5 10-5-10-5Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>
        Merge &amp; transform</button>
      <span class="hint">Ingests the ticked samples plus any pasted sources, then applies the chosen output shape.</span>
    </div>
  </form>

  {% if ran %}
    <div class="summary">
      <div class="stat"><b>{{ profiles|length }}</b> profile{{ '' if profiles|length == 1 else 's' }}</div>
      <div class="stat">Config:&nbsp;<b style="font-weight:600">{{ selected_config or 'Default' }}</b></div>
      {% if active_keywords %}<div class="stat"><span class="swatch" style="background:var(--accent)"></span>Ranked by&nbsp;<b style="font-weight:600">{{ active_keywords|join(', ') }}</b></div>{% endif %}
      {% if warnings %}<div class="stat"><span class="swatch" style="background:var(--amber)"></span><b>{{ warnings|length }}</b> warning{{ '' if warnings|length == 1 else 's' }}</div>{% endif %}
    </div>

    {% if warnings %}
      <div class="warns">
        <div class="whead">
          <svg viewBox="0 0 24 24"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          {{ warnings|length }} warning(s) &mdash; pipeline degraded gracefully
        </div>
        <ul>{% for w in warnings %}<li>{{ w }}</li>{% endfor %}</ul>
      </div>
    {% endif %}

    {% if profiles|length == 0 %}
      <div class="card"><span class="empty">No profiles produced for this selection.</span></div>
    {% endif %}

    {% for p in profiles %}
    <div class="card">
      <div class="chead">
        <div class="avatar">{{ p.initials }}</div>
        <div class="who">
          <h2>{{ p.name or "(no name)" }}</h2>
          {% if p.headline %}<div class="role">{{ p.headline }}</div>{% endif %}
          {% if p.id %}<div class="cid">{{ p.id }}</div>{% endif %}
        </div>
        {% if p.overall is not none %}
        <span class="conf" style="background:{{ p.overall_color }}"
          {% if p.boosted %}title="Data confidence {{ '%.0f'|format(p.base_overall*100) }}%, keyword-adjusted to {{ '%.0f'|format(p.overall*100) }}%"{% endif %}>
          <span class="cdot"></span>{{ '%.0f'|format(p.overall*100) }}%{% if p.boosted %}&nbsp;<span class="base">&middot; conf {{ '%.0f'|format(p.base_overall*100) }}%</span>{% endif %}</span>
        {% endif %}
      </div>

      {% if p.keywords_active %}
      <div class="kwrow">
        <span class="lead">{{ p.match_count }}/{{ active_keywords|length }} keywords</span>
        {% for kw in active_keywords %}
          {% if kw in p.matched %}
          <span class="kw hit"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>{{ kw }}</span>
          {% else %}
          <span class="kw miss">{{ kw }}</span>
          {% endif %}
        {% endfor %}
      </div>
      {% endif %}

      {% if p.emails or p.phones or p.location or p.links %}
      <div class="divider"></div>
      <div class="contact">
        {% if p.emails %}<div class="ci"><svg viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/></svg><span>{{ p.emails|join(', ') }}</span></div>{% endif %}
        {% if p.phones %}<div class="ci"><svg viewBox="0 0 24 24"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"/></svg><span>{{ p.phones|join(', ') }}</span></div>{% endif %}
        {% if p.location %}<div class="ci"><svg viewBox="0 0 24 24"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0Z"/><circle cx="12" cy="10" r="3"/></svg><span>{{ p.location }}</span></div>{% endif %}
        {% if p.links %}<div class="ci"><svg viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg><span>{{ p.links|join('   ·   ') }}</span></div>{% endif %}
      </div>
      {% endif %}

      {% if p.skills %}
      <div class="sec">Skills</div>
      <div>
        {% for sk in p.skills %}
        <span class="pill">{{ sk.name }}{% if sk.confidence is not none %}<span class="bar" title="{{ '%.0f'|format(sk.confidence*100) }}% confidence"><i style="width:{{ '%.0f'|format(sk.confidence*100) }}%"></i></span>{% endif %}</span>
        {% endfor %}
      </div>
      {% endif %}

      {% if p.experience %}
      <div class="sec">Experience</div>
      <div class="tl">
        {% for e in p.experience %}
        <div class="item">
          <div class="t">{{ e.title or '' }}{% if e.company %} <span class="c">· {{ e.company }}</span>{% endif %}</div>
          <div class="when">{{ e.start or '?' }} &rarr; {{ e.end or 'present' }}</div>
        </div>
        {% endfor %}
      </div>
      {% endif %}

      {% if p.education %}
      <div class="sec">Education</div>
      <div class="edu">
        {% for ed in p.education %}
        <div class="item"><span class="deg">{{ ed.degree or '' }}{% if ed.field %} in {{ ed.field }}{% endif %}</span>{% if ed.institution %} &mdash; {{ ed.institution }}{% endif %}{% if ed.end_year %} ({{ ed.end_year }}){% endif %}</div>
        {% endfor %}
      </div>
      {% endif %}

      {% if p.provenance %}
      <details><summary>Provenance &mdash; {{ p.provenance|length }} entries</summary>
        <table><thead><tr><th>Field</th><th>Source</th><th>Method</th></tr></thead><tbody>
        {% for pr in p.provenance %}<tr><td>{{ pr.field }}</td><td>{{ pr.source }}</td><td><span class="tag">{{ pr.method }}</span></td></tr>{% endfor %}
        </tbody></table>
      </details>
      {% endif %}

      <details><summary>Raw projected JSON</summary><pre>{{ p.raw }}</pre></details>
    </div>
    {% endfor %}
  {% endif %}
</main>
<script>
(function(){
  var SAMPLES = {
    recruiter_csv: `name,email,phone,current_company,title,location
Priya Sharma,priya.sharma@example.com,(415) 555-0142,Acme Corp,Senior Backend Engineer,"San Francisco, CA"`,
    ats_json: `{
  "applicant_name": "Priya Sharma",
  "contact": { "primaryEmail": "priya.sharma@example.com", "mobileNumber": "+1 415 555 0142" },
  "addr": { "city": "San Francisco", "state": "CA", "country": "USA" },
  "skillSet": ["Python", "k8s", "postgres"],
  "employmentHistory": [
    { "employer": "Acme Corp", "designation": "Senior Backend Engineer", "from": "Mar 2021", "to": "present" }
  ]
}`,
    resume: `Priya Sharma
Senior Backend Engineer
priya.sharma@example.com | github.com/priyasharma

EXPERIENCE
Senior Backend Engineer at Acme Corp, Mar 2021 to present
Backend Engineer at Globex, Jan 2018 - Feb 2021

EDUCATION
B.Tech in Computer Science, IIT Bombay, 2017

SKILLS
Python, Kubernetes, PostgreSQL, Go`,
    recruiter_notes: `Spoke with Priya Sharma (priya.sharma@example.com, 415-555-0142). Strong in Python and k8s. Currently a Senior Backend Engineer at Acme Corp in San Francisco.`
  };
  var box = document.getElementById('pastes');
  if (!box) return;
  function reset(row){ row.querySelector('.ptext').value=''; row.querySelector('.ptype').selectedIndex=0; }
  document.getElementById('addrow').addEventListener('click', function(){
    var clone = box.querySelector('.prow').cloneNode(true);
    reset(clone);
    box.appendChild(clone);
  });
  box.addEventListener('click', function(e){
    var t = e.target;
    if (t.classList.contains('del-btn')){
      var rows = box.querySelectorAll('.prow');
      if (rows.length > 1) t.closest('.prow').remove(); else reset(t.closest('.prow'));
    }
    if (t.classList.contains('sample-btn')){
      var row = t.closest('.prow'), sel = row.querySelector('.ptype');
      if (!sel.value) sel.value = 'recruiter_csv';
      row.querySelector('.ptext').value = SAMPLES[sel.value] || '';
    }
  });
})();
</script>
</body></html>"""


def _conf_color(c: Optional[float]) -> str:
    if c is None:
        return "#9ca3af"
    if c >= 0.8:
        return "#16a34a"      # green
    if c >= 0.5:
        return "#d97706"      # amber
    return "#dc2626"          # red


def _view_model(out: dict) -> dict:
    """Map an output dict (default OR custom-projected) onto fields the template
    can render with .get(). Unknown/renamed shapes degrade gracefully."""
    loc = out.get("location") or {}
    loc_str = None
    if isinstance(loc, dict):
        loc_str = ", ".join(v for v in (loc.get("city"), loc.get("region"), loc.get("country")) if v) or None
    elif isinstance(loc, str):
        loc_str = loc
    links = out.get("links") or {}
    link_vals = []
    if isinstance(links, dict):
        link_vals = [v for v in (links.get("linkedin"), links.get("github"), links.get("portfolio")) if v]
    skills = []
    for sk in out.get("skills", []) or []:
        if isinstance(sk, dict):
            skills.append({"name": sk.get("name"), "confidence": sk.get("confidence")})
        else:
            skills.append({"name": sk, "confidence": None})
    overall = out.get("overall_confidence")
    name = out.get("full_name") or out.get("name")
    parts = [w for w in (name or "").split() if w]
    initials = "".join(w[0] for w in parts[:2]).upper() or "?"
    return {
        "name": name,
        "initials": initials,
        "id": out.get("candidate_id"),
        "overall": overall,
        "overall_color": _conf_color(overall),
        "emails": out.get("emails") or ([out["email"]] if out.get("email") else []),
        "phones": out.get("phones") or ([out["phone"]] if out.get("phone") else []),
        "location": loc_str,
        "headline": out.get("headline"),
        "links": link_vals or ([out["github"]] if out.get("github") else []),
        "skills": skills,
        "experience": out.get("experience", []) or [],
        "education": out.get("education", []) or [],
        "provenance": out.get("provenance", []) or [],
        "raw": json.dumps(out, indent=2, ensure_ascii=False),
    }


def create_app():
    try:
        from flask import Flask, render_template_string, request
    except ImportError as exc:  # pragma: no cover - import guard
        raise SystemExit("Flask is not installed. Run: pip install -e \".[web]\"") from exc

    app = Flask(__name__)
    samples = _list_samples()
    configs = _list_configs()
    # sensible defaults: ingest everything so the merge is interesting out of the box
    default_selected = set(samples)

    @app.get("/")
    def index():
        return render_template_string(
            PAGE, samples=samples, configs=configs, ran=False,
            selected_sources=default_selected, selected_config="",
            paste_rows=[{"type": "", "text": ""}],
            keywords_str="", active_keywords=[],
            profiles=[], warnings=[])

    # custom-paste source type -> temp-file suffix (explicit type bypasses detection)
    _PASTE_EXT: Dict[str, str] = {
        "recruiter_csv": ".csv", "ats_json": ".json",
        "resume": "_resume.txt", "recruiter_notes": ".txt",
    }

    @app.post("/run")
    def run_pipeline():
        chosen = request.form.getlist("source")
        cfg_name = (request.form.get("config") or "").strip()

        # Collect any pasted custom sources (parallel arrays, one pair per row).
        ptypes = request.form.getlist("paste_type")
        ptexts = request.form.getlist("paste_text")
        paste_rows: List[dict] = []
        pasted_specs: List[SourceSpec] = []
        tmp_paths: List[str] = []
        for ptype, ptext in zip(ptypes, ptexts):
            paste_rows.append({"type": ptype, "text": ptext})  # echo back so input persists
            ptype = (ptype or "").strip()
            if not (ptext or "").strip() or ptype not in _PASTE_EXT:
                continue
            fd, tmp = tempfile.mkstemp(prefix="pasted_%s_" % ptype, suffix=_PASTE_EXT[ptype])
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(ptext)
            tmp_paths.append(tmp)
            pasted_specs.append(SourceSpec(path=tmp, type=ptype))
        if not paste_rows:
            paste_rows = [{"type": "", "text": ""}]

        # Convenience: if the user picked nothing at all, ingest every sample.
        if not chosen and not pasted_specs:
            chosen = list(samples)

        specs = [SourceSpec(path=os.path.join(SAMPLES_DIR, s)) for s in chosen] + pasted_specs
        config = OutputConfig.load(os.path.join(CONFIGS_DIR, cfg_name)) if cfg_name else None

        try:
            result = run(specs, config=config)
        finally:
            for tp in tmp_paths:  # don't leave temp files behind
                try:
                    os.remove(tp)
                except OSError:
                    pass

        # Optional recruiter keyword boost. Empty box => engine output untouched.
        keywords_raw = request.form.get("keywords", "")
        keywords = parse_keywords(keywords_raw)

        view_models: List[dict] = []
        for out, prof in zip(result.outputs, result.output_profiles):
            vm = _view_model(out)
            if keywords:
                frac, matched = keyword_match(prof, keywords)
                base = vm["overall"]
                vm.update(keywords_active=True, matched=matched,
                          match_count=len(matched), match_frac=frac)
                blended = blend_score(base, frac)
                if blended is not None:
                    vm.update(base_overall=base, overall=blended,
                              overall_color=_conf_color(blended), boosted=True)
                # rank keyword matches first, then by the engine's own score
                vm["_sort"] = (frac, base if base is not None else 0.0)
            view_models.append(vm)
        if keywords:
            # keyword run: most relevant first, then by the engine's own score
            view_models.sort(key=lambda v: v["_sort"], reverse=True)
        else:
            # default run: order by confidence descending (highest first); records
            # with no score (configs that hide it) sort to the end.
            view_models.sort(key=lambda v: (v["overall"] is None,
                                            -(v["overall"] if v["overall"] is not None else 0.0)))

        # Warnings are suppressed in the web UI only. The pipeline still
        # collects them (result.warnings) for the CLI/logs and continues to
        # degrade gracefully per-source; we just don't surface them here.
        return render_template_string(
            PAGE, samples=samples, configs=configs, ran=True,
            selected_sources=set(chosen), selected_config=cfg_name,
            paste_rows=paste_rows, keywords_str=keywords_raw, active_keywords=keywords,
            profiles=view_models, warnings=[])

    return app


def main() -> int:
    app = create_app()
    print("Candidate Transformer UI -> http://127.0.0.1:5000  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5000, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
