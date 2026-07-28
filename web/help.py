"""Help — User Guide + Technical Architecture, rendered from the docs/ markdown.

The markdown is rendered client-side with marked.js (already loaded in the shell),
scoped by a .mddoc wrapper so it doesn't fight the app CSS.
"""

from __future__ import annotations

import json
from pathlib import Path

from web.ui import section_title
from fasthtml.common import *

DOCS = Path(__file__).resolve().parent.parent / "docs"

MD_CSS = Style("""
.mddoc{max-width:920px;font-size:14.5px;color:#48484f}
.mddoc h1{font-size:23px;margin:0 0 6px;color:#48484f}
.mddoc h2{font-size:18px;margin:26px 0 8px;color:var(--navy);border-bottom:1px solid var(--line);padding-bottom:4px}
.mddoc h3{font-size:15px;margin:18px 0 6px;color:var(--navy)}
.mddoc p,.mddoc li{line-height:1.6}
.mddoc code{background:#f0eef3;padding:1px 5px;border-radius:4px;font-size:12.5px}
.mddoc pre{background:#f5f6f4;border:1px solid var(--line);border-radius:8px;padding:12px 14px;overflow-x:auto}
.mddoc pre code{background:none;padding:0}
.mddoc table{margin:10px 0}
.mddoc blockquote{border-left:3px solid var(--accent);margin:10px 0;padding:2px 14px;color:#6b7686;background:#F1FAFA}
.mddoc a{color:var(--navy2)}
""")


def _render(md_file: str, title: str, downloads=None):
    path = DOCS / md_file
    md = path.read_text() if path.exists() else f"# {title}\n\n_Document not found._"
    dl = (Div(*downloads, style="margin:6px 0 16px;display:flex;gap:10px;flex-wrap:wrap")
          if downloads else "")
    return (
        MD_CSS,
        dl,
        Div(id="mddoc", cls="mddoc"),
        Script(f"document.getElementById('mddoc').innerHTML = "
               f"(window.marked?marked.parse({json.dumps(md)}):{json.dumps(md)});"),
    )


def user_guide_content():
    downloads = [
        A("⬇ User Guide (PDF)", href="/help/user-guide-pdf", cls="btn sm", target="_blank"),
        A("⬇ User Guide (PPTX)", href="/help/user-guide-pptx", cls="btn sm ghost"),
        A("🛠 Technical Architecture", href="/help/architecture", cls="btn sm ghost"),
    ]
    return _render("fastppm_user_guide.md", "User Guide", downloads)


def architecture_content():
    return _render("architecture.md", "Technical Architecture")
