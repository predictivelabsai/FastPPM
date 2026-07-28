"""Shared UI: design system, the 3-pane shell, and reusable components.

FastPPM's navy/teal design system provides a left navigation pane, centre
content, and right copilot rail. FastPPM puts the chat-first analyst at the
centre; page modules import ``Page`` and the component helpers here.
"""

from __future__ import annotations

from fasthtml.common import *

import ppmstore as store

BRAND = "FastPPM"

# ── Domain labels / colours ────────────────────────────────────────────────

INITIATIVE_TYPES = {
    "program": "Programme", "workstream": "Workstream",
    "ai_use_case": "AI use case", "value_initiative": "Value initiative",
}
TYPE_COLOR = {"program": "#0B2942", "workstream": "#123B5D",
              "ai_use_case": "#00A6A6", "value_initiative": "#2b6cb0"}

STATUSES = ["not_started", "in_progress", "on_track", "at_risk", "delayed",
            "complete", "on_hold"]
STATUS_LABELS = {
    "not_started": "Not started", "in_progress": "In progress",
    "on_track": "On track", "at_risk": "At risk", "delayed": "Delayed",
    "complete": "Complete", "on_hold": "On hold",
}
STATUS_COLOR = {
    "not_started": "#7a7a85", "in_progress": "#2b6cb0", "on_track": "#1c7c44",
    "at_risk": "#b06b00", "delayed": "#c0392b", "complete": "#0B2942",
    "on_hold": "#7a7a85",
}
RAG_COLOR = {"G": "#1c7c44", "A": "#b06b00", "R": "#c0392b"}
RAG_LABEL = {"G": "Green", "A": "Amber", "R": "Red"}
RAG_BG = {"G": "#eaf5ee", "A": "#fdf0e3", "R": "#fbeaea"}
VALUE_CAT_LABELS = {"ebitda": "EBITDA", "cost_savings": "Cost savings",
                    "revenue": "Revenue", "synergy": "Synergy", "other": "Other"}
DOC_STATUS_COLOR = {"uploaded": "#7a7a85", "parsing": "#2b6cb0",
                    "extracted": "#b06b00", "merged": "#1c7c44", "error": "#c0392b"}

NAV = [
    ("Chat", "/"),
    ("Dashboard", "/dashboard"),
    ("Initiatives", "/initiatives"),
    ("Gantt", "/gantt"),
    ("Documents", "/documents"),
    ("Value", "/value"),
    ("Prompts", "/prompts"),
]

HELP_NAV = [
    ("📘 User Guide", "/help/guide"),
    ("🛠 Technical Architecture", "/help/architecture"),
]

SUGGESTIONS = [
    "What's the overall status of the Value Creation Plan?",
    "Which initiatives are red or at risk, and why?",
    "Show me the top value drivers by realised benefit",
    "What are the top 5 risks across the programme?",
    "How much value have we realised vs target?",
]


# ── Formatting ──────────────────────────────────────────────────────────────

def money(v, dp: int = 1) -> str:
    v = float(v or 0)
    if abs(v) >= 1_000_000:
        return f"£{v/1_000_000:.{dp}f}m"
    if abs(v) >= 1_000:
        return f"£{v/1_000:.0f}k"
    return f"£{v:.0f}"


def pct(v, dp: int = 0) -> str:
    return "—" if v is None else f"{float(v):.{dp}f}%"


def num(v, dp: int = 1) -> str:
    return "—" if v is None else f"{float(v):.{dp}f}"


def short_date(d) -> str:
    return (d or "—")[:10] if d else "—"


# ── Badges / components ─────────────────────────────────────────────────────

def _chip(text_, color, bg=None):
    bg = bg or (color + "1a")
    return Span(text_, style=f"display:inline-block;background:{bg};color:{color};"
                "border-radius:20px;padding:2px 10px;font-size:11px;font-weight:600;"
                "white-space:nowrap")


def status_badge(s):
    return _chip(STATUS_LABELS.get(s, s or "—"), STATUS_COLOR.get(s, "#7a7a85"))


def type_badge(t):
    return _chip(INITIATIVE_TYPES.get(t, t or "—"), TYPE_COLOR.get(t, "#123B5D"))


def rag_badge(r):
    r = (r or "").upper()
    if r not in RAG_COLOR:
        return _chip("—", "#9a93a6")
    return _chip(RAG_LABEL[r], RAG_COLOR[r], RAG_BG[r])


def rag_dot(r):
    r = (r or "").upper()
    col = RAG_COLOR.get(r, "#cfcfd6")
    return Span(style=f"display:inline-block;width:11px;height:11px;border-radius:50%;"
                f"background:{col};vertical-align:middle")


def doc_status_badge(s):
    return _chip(s.title() if s else "—", DOC_STATUS_COLOR.get(s, "#7a7a85"))


def metric(label, value, sub=None, accent="#123B5D"):
    return Div(
        Div(label, style="font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#7a7a85"),
        Div(value, style=f"font-size:25px;font-weight:700;color:{accent};margin-top:2px"),
        (Div(sub, style="font-size:12px;color:#7a7a85;margin-top:2px") if sub else ""),
        cls="metric")


def progress_bar(p, accent="#00A6A6"):
    v = int(p or 0)
    return Div(Div(Span(style=f"width:{v}%;background:{accent}"), cls="bar"),
               Span(f"{v}%", style="font-size:12px;color:#7a7a85;margin-left:6px"),
               style="display:flex;align-items:center;gap:2px")


def section_title(t, sub=None):
    return Div(H1(t, style="margin:0;font-size:22px;color:#48484f"),
               (P(sub, style="margin:3px 0 0;color:#7a7a85;font-size:13.5px") if sub else ""),
               style="margin:4px 0 18px")


def download_buttons(base, kind):
    """⬇ CSV / ⬇ XLSX links for a table. ``base`` is /document/{id} or
    /initiative/{id}; the export route is ``{base}/export``."""
    return Span(
        A("⬇ CSV", href=f"{base}/export?kind={kind}&fmt=csv", cls="btn sm ghost"),
        A("⬇ XLSX", href=f"{base}/export?kind={kind}&fmt=xlsx", cls="btn sm ghost"),
        style="display:inline-flex;gap:6px")


def card_header(title, buttons=None):
    """A card heading row with optional right-aligned action buttons."""
    return Div(H3(title, style="margin:0"), (buttons or ""),
               style="display:flex;justify-content:space-between;align-items:center;"
               "gap:10px;margin-bottom:12px;flex-wrap:wrap")


# ── Stylesheet (FastPPM palette) ────────────────────────────────────────────────

CSS = Style("""
:root{--navy:#123B5D;--navy2:#0B2942;--accent:#00A6A6;--bg:#f5f6f4;--line:#D8E5EA;
--green:#1c7c44;--amber:#b06b00;--red:#c0392b;--text:#48484f;--muted:#7a7a85;--panel:#fff;}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
color:var(--text);background:var(--bg);line-height:1.5}
a{color:var(--navy2);text-decoration:none}a:hover{text-decoration:underline}
.app{display:grid;grid-template-columns:260px 1fr 400px;height:100vh;overflow:hidden}
.pane{height:100vh;overflow-y:auto}
.left{background:var(--navy);color:#E7F1F5;padding:0}
.left .brand{font-weight:700;font-size:18px;color:#fff;padding:16px 18px;border-bottom:1px solid #45114a}
.left .brand span{color:var(--accent)}
.left .brand small{display:block;font-weight:400;font-size:11px;color:#A9C7D8;margin-top:2px}
.left a{color:#E7F1F5;display:block}
.section{padding:12px 16px;border-bottom:1px solid #45114a}
.section .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:#A9C7D8;margin-bottom:8px}
.navlink{padding:7px 9px;border-radius:6px;font-size:14px}.navlink:hover{background:#174F73;text-decoration:none}
.navlink.on{background:#174F73;font-weight:600}
.newchat{display:block;background:var(--accent);color:#fff;text-align:center;font-weight:600;
padding:9px;border-radius:8px;margin:12px 16px}.newchat:hover{text-decoration:none;filter:brightness(1.05)}
details.tree{margin:2px 0}details.tree>summary{cursor:pointer;font-size:13px;padding:3px 0;list-style:none}
details.tree>summary::-webkit-details-marker{display:none}
details.tree>summary:before{content:"▸ ";color:#A9C7D8}details.tree[open]>summary:before{content:"▾ "}
.tree .ws{font-weight:600;color:#F1F8FA}
.prjlink{margin-left:16px;display:block;font-size:12.5px;color:#E7F1F5;padding:2px 0}
.prjlink:hover{color:#fff;text-decoration:none}
.sess{font-size:13px;padding:4px 8px;border-radius:6px;display:block;color:#E7F1F5}.sess:hover{background:#174F73}
.pane.centerdoc{display:block;overflow-y:auto;background:#fbfcfd}
.centerdoc .wrap{max-width:1040px;margin:0 auto;padding:24px 28px}
/* chat */
.center{display:flex;flex-direction:column;background:#fbfcfd}
.center .chead{padding:14px 22px;border-bottom:1px solid var(--line);font-weight:600;color:var(--navy)}
.msgs{flex:1;overflow-y:auto;padding:22px;display:flex;flex-direction:column;gap:14px}
.bubble{max-width:760px;padding:12px 16px;border-radius:12px;font-size:14.5px;white-space:normal}
.bubble.user{align-self:flex-end;background:var(--navy);color:#fff;border-bottom-right-radius:3px}
.bubble.assistant{align-self:flex-start;background:#fff;border:1px solid var(--line);border-bottom-left-radius:3px}
.bubble.assistant pre{white-space:pre-wrap}
.bubble.assistant table{margin:6px 0}
.toolchip{display:inline-block;font-size:11px;background:#eef4fb;color:var(--navy2);border:1px solid #d6e3f1;
border-radius:20px;padding:1px 9px;margin:2px 4px 2px 0}
/* Conversational analytics — table + chart-offer chips + inline Plotly */
.dswrap{margin:10px 0 2px}
.dstitle{font-weight:600;color:var(--navy);font-size:13.5px;margin:4px 0 6px}
.dtable{border-collapse:collapse;width:100%;font-size:13px;margin:0 0 8px}
.dtable th{text-align:left;color:#7a7a85;font-weight:600;border-bottom:2px solid var(--line);padding:5px 10px;font-size:11.5px;text-transform:uppercase;letter-spacing:.3px}
.dtable td{border-bottom:1px solid var(--line);padding:5px 10px}
.dtable td.num{text-align:right;font-variant-numeric:tabular-nums}
.chartchips{display:flex;align-items:center;flex-wrap:wrap;gap:6px;font-size:12px;color:#7a7a85;margin:2px 0}
.chip{background:#fff;border:1px solid var(--line);border-radius:20px;padding:3px 12px;font-size:12px;
color:var(--navy);cursor:pointer;font-weight:500}
.chip:hover{border-color:var(--accent)}
.chip.on{background:var(--accent);border-color:var(--accent);color:#fff}
.chartbox{margin-top:8px}
.vhkpi{display:flex;flex-direction:column;align-items:flex-start;padding:14px 4px}
.vhkpi .v{font-size:34px;font-weight:800;color:var(--navy)}
.vhkpi .l{font-size:12.5px;color:#7a7a85}
.cards{display:flex;flex-wrap:wrap;gap:8px;padding:8px 22px}
.scard{background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px 11px;font-size:12.5px;
cursor:pointer;max-width:340px}.scard:hover{border-color:var(--accent);color:var(--navy)}
.composer{padding:14px 22px;border-top:1px solid var(--line);background:#fff;display:flex;gap:10px}
.composer textarea{flex:1;resize:none;border:1px solid var(--line);border-radius:10px;padding:11px;font:inherit;height:48px}
.composer button{background:var(--navy);color:#fff;border:none;border-radius:10px;padding:0 20px;font-weight:600;cursor:pointer}
.right{background:#fff;border-left:1px solid var(--line);display:flex;flex-direction:column}
.right .rhead{padding:13px 18px;border-bottom:1px solid var(--line);font-weight:600;color:var(--navy)}
.rbody{flex:1;overflow-y:auto;padding:14px 18px}
.copilot-pane .msgs{padding:16px}.copilot-pane .composer{padding:12px 14px}
/* content */
.wrap h1{font-size:22px;margin:0 0 4px;color:#48484f}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:4px 0 20px}
.metric{background:#fff;border:1px solid var(--line);border-radius:10px;padding:13px 15px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:18px}
.card h3{margin:0 0 12px;font-size:15px;color:var(--navy)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:9px 13px;border-bottom:1px solid var(--line);font-size:13.5px;vertical-align:middle}
th{background:#fbfbfc;color:var(--muted);font-size:11px;text-transform:uppercase}
tr:last-child td{border-bottom:none}tbody tr:hover{background:#fafbfc}
.bar{height:7px;border-radius:5px;background:#eee;overflow:hidden;min-width:60px;flex:1}
.bar>span{display:block;height:100%;background:var(--accent)}
.btn{display:inline-block;background:var(--navy);color:#fff;padding:9px 16px;border-radius:7px;font-size:14px;border:none;cursor:pointer}
.btn:hover{filter:brightness(1.06);text-decoration:none}
.btn.ghost{background:#fff;color:var(--navy);border:1px solid var(--line)}
.btn.sm{padding:5px 11px;font-size:12.5px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.filters a{font-size:12.5px;padding:5px 11px;border:1px solid var(--line);border-radius:20px;background:#fff;color:var(--muted)}
.filters a.on{background:var(--navy);color:#fff;border-color:var(--navy)}
.kanban{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.kcol{background:#f3f1f6;border-radius:10px;padding:10px;min-height:120px}
.kcol h4{margin:0 0 8px;font-size:12px;text-transform:uppercase;color:var(--muted);letter-spacing:.5px}
.kcard{background:#fff;border:1px solid var(--line);border-radius:8px;padding:9px 10px;margin-bottom:8px;font-size:12.5px}
.kcard a{font-weight:600;color:var(--navy)}
dl.meta{display:grid;grid-template-columns:150px 1fr;gap:6px 14px;font-size:13.5px;margin:0}
dl.meta dt{color:var(--muted)}
form.std label{display:block;font-size:12.5px;color:var(--muted);margin:10px 0 3px;font-weight:600}
form.std input,form.std select,form.std textarea{width:100%;padding:9px;border:1px solid var(--line);border-radius:7px;font:inherit}
.dropzone{border:2px dashed var(--accent);border-radius:12px;padding:30px;text-align:center;background:#F1FAFA;color:var(--navy)}
.dropzone input{margin-top:10px}
.banner{padding:11px 15px;border-radius:8px;margin-bottom:16px;font-size:13.5px}
.banner.ok{background:#eaf5ee;color:#1c7c44}.banner.warn{background:#fdf0e3;color:#b06b00}
.form{background:#fff;border:1px solid var(--line);border-radius:10px;padding:24px;max-width:380px;margin:60px auto}
.form input{width:100%;padding:10px;border:1px solid var(--line);border-radius:7px;margin:6px 0 14px}
.pill-row{display:flex;gap:8px;flex-wrap:wrap}
""")

MARKED = Script(src="https://cdn.jsdelivr.net/npm/marked/marked.min.js")
PLOTLY = Script(src="https://cdn.plot.ly/plotly-2.35.2.min.js")

# Diamond favicon — inline SVG data URI in the brand teal/navy. A facetted
# gem: top + bottom triangles for the table/pavilion, a lighter left facet.
_FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<polygon points='6,12 16,3 26,12 16,29' fill='#00A6A6'/>"
    "<polygon points='6,12 16,3 16,12' fill='#39C6C1'/>"
    "<polygon points='16,12 16,3 26,12' fill='#008C95'/>"
    "<polygon points='6,12 26,12 16,29' fill='#123B5D'/>"
    "<polygon points='6,12 16,12 16,29' fill='#166B7A'/>"
    "</svg>"
)
FAVICON = Link(rel="icon", type="image/svg+xml",
               href="data:image/svg+xml,"
               + _FAVICON_SVG.replace("#", "%23").replace("<", "%3C")
                             .replace(">", "%3E").replace("'", "%27"))

# Trix WYSIWYG (single include; clean HTML out, preserves code blocks). Shared by
# the Prompt Manager and the report editor.
TRIX_CSS = Link(rel="stylesheet", href="https://unpkg.com/trix@2.1.15/dist/trix.css")
TRIX_JS = Script(src="https://unpkg.com/trix@2.1.15/dist/trix.umd.min.js")
TRIX_STYLE = Style("""
trix-toolbar .trix-button-group--file-tools{display:none}
trix-editor{min-height:140px;background:#fff;border:1px solid var(--line);border-radius:8px;
  padding:12px;font-size:13.5px;line-height:1.5}
trix-editor pre{background:#f5f6f4;border:1px solid var(--line);border-radius:6px;
  padding:10px 12px;font-size:12px;white-space:pre-wrap}
""")


# ── Left pane (nav + initiative tree by workstream) ─────────────────────────

def _tree():
    inis = [i for i in store.list_initiatives() if i["type"] != "program"]
    by_ws: dict[str, list] = {}
    for i in inis:
        by_ws.setdefault(i.get("workstream") or "Other", []).append(i)
    nodes = []
    for ws in sorted(by_ws):
        links = [A(i["name"], href=f"/initiative/{i['id']}", cls="prjlink")
                 for i in sorted(by_ws[ws], key=lambda x: x["name"])]
        nodes.append(Details(Summary(ws, cls="ws"), *links, cls="tree"))
    return Div(*nodes)


def left_pane(sess, active=""):
    email = sess.get("email", "") if sess else ""
    sessions = store.list_chat_sessions(email, limit=8) if email else []
    nav = [A(label, href=href, cls="navlink" + (" on" if href == active else ""))
           for label, href in NAV]
    helpnav = [A(label, href=href, cls="navlink" + (" on" if href == active else ""))
               for label, href in HELP_NAV]
    recent = ([A(s["title"] or "Untitled", href=f"/?sid={s['id']}", cls="sess")
               for s in sessions] or [Div("No chats yet", style="font-size:12px;color:#A9C7D8")])
    return Div(
        Div(Span(BRAND), Small("Project and Portfolio Management"),
            cls="brand"),
        A("+ New chat", href="/", cls="newchat"),
        Div(Div("Navigate", cls="lbl"), *nav, cls="section"),
        Div(Div("Recent chats", cls="lbl"), *recent, cls="section"),
        Div(Div("Initiatives", cls="lbl"), _tree(), cls="section"),
        Div(Div("Help", cls="lbl"), *helpnav, cls="section"),
        Div(A("Sign out", href="/logout", style="font-size:12px;color:#A9C7D8"), cls="section"),
        cls="pane left")


def copilot_rail():
    cards = [Div(s, cls="scard", onclick="copAsk(this.textContent)") for s in SUGGESTIONS[:4]]
    return Div(
        Div("Ask FastPPM", cls="rhead"),
        Div(Div(*cards, style="display:flex;flex-direction:column;gap:7px"),
            Div(id="cop-msgs", style="margin-top:12px;display:flex;flex-direction:column;gap:10px"),
            cls="rbody"),
        Div(Textarea(placeholder="Ask about the programme…", id="cop-inp",
                     onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();copSend();}"),
            Button("Ask", onclick="copSend()"), cls="composer"),
        cls="pane right copilot-pane")


def Page(sess, *content, title=None, active="", copilot=True):
    title = title or f"{BRAND}"
    center = Div(Div(*content, cls="wrap"), cls="pane center centerdoc")
    right = copilot_rail() if copilot else Div(cls="pane right")
    return (Title(title), CSS,
            Div(left_pane(sess, active), center, right, cls="app"),
            MARKED, PLOTLY, VH_STREAM_JS, COPILOT_JS)


# Shared chat engine for both surfaces (home centre + copilot rail): one SSE
# streamer, plus the generative-analytics renderer that turns a `dataset` event
# into a table + chart-offer chips and draws an inline Plotly chart on click.
VH_STREAM_JS = Script(r"""
window.VH_PALETTE=["#123B5D","#00A6A6","#2b6cb0","#1c7c44","#b06b00","#8a5cd1","#c0392b"];
function mdp(t){return window.marked?marked.parse(t):t;}
function mdParse(t){return mdp(t);}  /* back-compat */
function vhEsc(s){return (''+s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function vhFmt(v,type){
  if(v==null||v==='')return '';
  if(type==='currency'){var n=+v;if(Math.abs(n)>=1e6)return '£'+(n/1e6).toFixed(1)+'m';
    if(Math.abs(n)>=1e3)return '£'+(n/1e3).toFixed(0)+'k';return '£'+n;}
  if(type==='pct')return v+'%';
  if(type==='number')return ''+v;
  return vhEsc(v);
}
function vhCol(ds,k){return (ds.columns||[]).find(function(c){return c.key===k;})||{};}
function vhTable(ds){
  var h='<table class="dtable"><thead><tr>';
  ds.columns.forEach(function(c){h+='<th>'+vhEsc(c.label)+'</th>';});
  h+='</tr></thead><tbody>';
  ds.rows.forEach(function(r){h+='<tr>';ds.columns.forEach(function(c){
    var num=(c.type==='currency'||c.type==='number'||c.type==='pct');
    h+='<td'+(num?' class="num"':'')+'>'+vhFmt(r[c.key],c.type)+'</td>';});h+='</tr>';});
  return h+'</tbody></table>';
}
var VH_CHART_LABEL={bar:'📊 Bar',pie:'🥧 Pie',line:'📈 Line',donut:'🍩 Donut',kpi:'🔢 Value'};
function vhBuildFigure(ds,type){
  var x=ds.rows.map(function(r){return r[ds.x];});
  var measures=(ds.y||[]).map(function(k){return {key:k,label:vhCol(ds,k).label||k};});
  var colors=(ds.meta&&ds.meta.colors)||null;
  var layout={margin:{l:52,r:14,t:8,b:64},height:300,paper_bgcolor:'white',plot_bgcolor:'white',
    font:{family:'-apple-system,Segoe UI,Roboto,sans-serif',size:12,color:'#48484f'},
    legend:{orientation:'h',y:-0.28},barmode:'group',xaxis:{automargin:true},yaxis:{automargin:true}};
  var data;
  if(type==='pie'||type==='donut'){
    var k=measures[0].key;
    data=[{type:'pie',labels:x,values:ds.rows.map(function(r){return r[k];}),
      hole:type==='donut'?0.5:0,
      marker:{colors:colors?x.map(function(l){return colors[l]||window.VH_PALETTE[0];}):window.VH_PALETTE}}];
    layout.height=320;layout.margin={l:8,r:8,t:8,b:8};
  } else if(type==='line'){
    data=measures.map(function(m,i){return {type:'scatter',mode:'lines+markers',name:m.label,x:x,
      y:ds.rows.map(function(r){return r[m.key];}),
      line:{color:window.VH_PALETTE[i%window.VH_PALETTE.length],width:2.5}};});
  } else {
    data=measures.map(function(m,i){return {type:'bar',name:m.label,x:x,
      y:ds.rows.map(function(r){return r[m.key];}),
      marker:{color:(colors&&measures.length===1)?x.map(function(l){return colors[l]||window.VH_PALETTE[0];})
        :window.VH_PALETTE[i%window.VH_PALETTE.length]}};});
  }
  return {data:data,layout:layout};
}
function vhKpi(ds){
  var k=(ds.y||[])[0],c=vhCol(ds,k),r=ds.rows[0]||{};
  return '<div class="vhkpi"><div class="v">'+vhFmt(r[k],c.type)+'</div><div class="l">'+
    vhEsc(c.label||ds.title||'')+'</div></div>';
}
function vhRenderDataset(bubble,ds){
  var wrap=document.createElement('div');wrap.className='dswrap';
  var chips='';(ds.offered||['bar']).forEach(function(t){
    chips+='<button class="chip'+(t===ds.recommended?' on':'')+'" data-t="'+t+'">'+
      (VH_CHART_LABEL[t]||t)+'</button>';});
  wrap.innerHTML=(ds.title?'<div class="dstitle">'+vhEsc(ds.title)+'</div>':'')+vhTable(ds)+
    '<div class="chartchips">See as: '+chips+'</div><div class="chartbox" style="display:none"></div>';
  bubble.appendChild(wrap);
  var box=wrap.querySelector('.chartbox');
  function draw(type){
    wrap.querySelectorAll('.chip').forEach(function(c){c.classList.toggle('on',c.dataset.t===type);});
    box.style.display='';
    if(type==='kpi'){box.innerHTML=vhKpi(ds);return;}
    var fig=vhBuildFigure(ds,type);
    if(window.Plotly)Plotly.newPlot(box,fig.data,fig.layout,{displayModeBar:false,responsive:true});
    else box.innerHTML='<div style="color:#9aa;font-size:12px">(chart library loading…)</div>';
  }
  wrap.querySelectorAll('.chip').forEach(function(c){
    c.addEventListener('click',function(){draw(c.dataset.t);});});
}
function vhBubble(box,role,html){var d=document.createElement('div');d.className='bubble '+role;
  d.innerHTML=html;box.appendChild(d);box.scrollTop=box.scrollHeight;return d;}
async function vhStream(boxId,inpId){
  if(window._vhStreaming)return false;
  var i=document.getElementById(inpId);var msg=i.value.trim();if(!msg)return false;
  var box=document.getElementById(boxId);window._vhStreaming=true;
  vhBubble(box,'user',vhEsc(msg));i.value='';
  var b=vhBubble(box,'assistant','<div class="btext"><span style="color:#9aa">…</span></div>');
  var bt=b.querySelector('.btext');var acc='';
  try{
    var resp=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({msg:msg,sid:''})});
    var rd=resp.body.getReader(),dec=new TextDecoder(),buf='';
    while(true){var r=await rd.read();if(r.done)break;buf+=dec.decode(r.value,{stream:true});
      var idx;while((idx=buf.indexOf('\n\n'))>=0){var raw=buf.slice(0,idx);buf=buf.slice(idx+2);
        var ev=raw.match(/^event: (.*)$/m),da=raw.match(/^data: (.*)$/m);if(!ev||!da)continue;
        var type=ev[1],data=JSON.parse(da[1]);
        if(type==='token'){if(acc==='')bt.innerHTML='';acc+=data.text;bt.innerHTML=mdp(acc);}
        else if(type==='tool_start'){var c=document.createElement('span');c.className='toolchip';
          c.textContent='⚙ '+data.name;bt.appendChild(c);}
        else if(type==='dataset'){vhRenderDataset(b,data);}
        box.scrollTop=box.scrollHeight;}}
  }catch(e){bt.innerHTML='<span style="color:#c0392b">(connection error)</span>';}
  window._vhStreaming=false;return false;
}
/* Re-render persisted datasets (and parse markdown) when reopening a chat. */
function vhHydrate(){
  document.querySelectorAll('#msgs .bubble.assistant, #cop-msgs .bubble.assistant').forEach(function(b){
    if(b.querySelector('.btext'))return;  /* already structured (live) */
    var dsets=[];
    [].slice.call(b.querySelectorAll('script[type="application/vh-dataset"]')).forEach(function(s){
      try{dsets=dsets.concat(JSON.parse(s.textContent));}catch(e){}s.parentNode.removeChild(s);});
    b.innerHTML='<div class="btext">'+mdp(b.innerHTML)+'</div>';
    dsets.forEach(function(ds){vhRenderDataset(b,ds);});
  });
}
document.addEventListener('DOMContentLoaded',vhHydrate);
""")

COPILOT_JS = Script("""
function copAsk(t){document.getElementById('cop-inp').value=t;copSend();}
function copSend(){vhStream('cop-msgs','cop-inp');}
""")
