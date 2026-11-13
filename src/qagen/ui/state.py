"""Session-state helpers (single source of truth for UI data)."""
from __future__ import annotations

import streamlit as st

from ..llm.ollama_client import OllamaClient
from ..models import Requirement, TestCase
from ..services.generator import TestCaseGenerator

DEFAULTS = {
    "requirements": [], "cases": [], "source_name": "", "analyzed": False,
    "gen_stats": [], "test_data": {}, "last_gen_info": None,
}


def init() -> None:
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v if not isinstance(v, (list, dict)) else type(v)())


@st.cache_resource
def client() -> OllamaClient:
    return OllamaClient()


@st.cache_data(ttl=20, show_spinner=False)
def health():
    return client().health_check()


def generator() -> TestCaseGenerator:
    if "generator" not in st.session_state:
        st.session_state.generator = TestCaseGenerator(client())
    return st.session_state.generator


def reqs() -> list[Requirement]:
    return st.session_state.requirements


def cases() -> list[TestCase]:
    return st.session_state.cases


def reset_downstream() -> None:
    st.session_state.update(cases=[], analyzed=False, gen_stats=[], test_data={}, last_gen_info=None)
    st.session_state.pop("generator", None)
