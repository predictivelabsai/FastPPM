"""Plotly → inline-HTML helper. plotly.js is loaded once per page (ui.PLOTLY)."""

from __future__ import annotations

from fasthtml.common import NotStr

PALETTE = ["#123B5D", "#00A6A6", "#2b6cb0", "#1c7c44", "#b06b00", "#8a5cd1", "#c0392b"]


def render(fig, height: int = 340) -> NotStr:
    fig.update_layout(
        margin=dict(l=10, r=10, t=28, b=10), height=height,
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family="-apple-system,Segoe UI,Roboto,sans-serif", size=12, color="#48484f"),
        legend=dict(orientation="h", y=-0.18))
    return NotStr(fig.to_html(include_plotlyjs=False, full_html=False,
                              config={"displayModeBar": False}))
