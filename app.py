"""Entry point:  streamlit run app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="QA Test Case Agent", page_icon="✅", layout="wide")

from qagen.logging_setup import setup_logging  # noqa: E402
from qagen.ui import pages, state, theme  # noqa: E402

setup_logging()
theme.apply()
state.init()
try:
    pages.ROUTES[pages.sidebar()]()
except Exception as exc:  # last-resort guard so the user never sees a raw traceback
    import logging
    logging.getLogger("app").exception("Unhandled UI error")
    st.error(f"Unexpected error: {exc}. Details were written to logs/app.log.")
