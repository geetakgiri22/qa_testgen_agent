"""Visual identity: calm slate + teal, Segoe UI/system fonts (works offline on Windows 11)."""
import streamlit as st

CSS = """
<style>
html, body, [class*="css"] { font-family: "Segoe UI", "IBM Plex Sans", system-ui, sans-serif; }
h1, h2, h3 { letter-spacing: -0.01em; font-weight: 600; color: #14262B; }
h1 { font-size: 1.7rem; margin-bottom: .15rem; }
.page-sub { color: #55676C; margin: 0 0 1.1rem 0; max-width: 70ch; }
section[data-testid="stSidebar"] { background: #14262B; }
section[data-testid="stSidebar"] * { color: #DCE7E5 !important; }
section[data-testid="stSidebar"] .stRadio label { padding: .28rem .2rem; }
div[data-testid="stMetric"] { background: #FFFFFF; border: 1px solid #D5DCD8; border-radius: 6px; padding: .7rem .9rem; }
div[data-testid="stMetricValue"] { font-size: 1.6rem; font-variant-numeric: tabular-nums; }
.status-pill { display: inline-block; padding: .12rem .55rem; border-radius: 999px; font-size: .8rem; font-weight: 600; }
.pill-ok { background: #D8EFE3; color: #165B3A; } .pill-bad { background: #F8DCD6; color: #8A2A1A; }
.pill-warn { background: #F7EBC8; color: #6B5210; }
.stage { border-left: 3px solid #C3CCC8; padding: .15rem 0 .15rem .75rem; margin-bottom: .5rem; }
.stage.done { border-color: #0F6E78; }
.stage b { display: block; }
:focus-visible { outline: 2px solid #0F6E78 !important; outline-offset: 2px; }
</style>
"""


def apply() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def header(title: str, sub: str) -> None:
    st.title(title)
    st.markdown(f'<p class="page-sub">{sub}</p>', unsafe_allow_html=True)


def pill(text: str, kind: str = "ok") -> str:
    return f'<span class="status-pill pill-{kind}">{text}</span>'
