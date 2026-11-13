"""Executes every page function against a stubbed `streamlit` to catch plain-Python errors.
This does NOT replace opening the real app; it only proves the page code runs end to end."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

here = Path(__file__).resolve().parent
sys.path[:0] = [str(here), str(here.parent / "src")]


class SS(dict):
    __getattr__ = dict.get
    def __setattr__(self, k, v): self[k] = v


st = MagicMock()
st.session_state = SS()
st.cache_resource = lambda f: f
def _cache_data(**kw):
    def deco(f):
        f.clear = lambda: None
        return f
    return deco
st.cache_data = _cache_data
st.button.return_value = False
st.toggle.return_value = False
st.checkbox.return_value = False
st.selectbox.side_effect = lambda label, opts, *a, **k: opts[0]
st.multiselect.side_effect = lambda label, opts, default=None, **k: default or []
st.columns.side_effect = lambda n: [MagicMock() for _ in range(n if isinstance(n, int) else len(n))]
st.tabs.side_effect = lambda labels: [MagicMock() for _ in labels]
sys.modules["streamlit"] = st

from mock_ollama import start  # noqa: E402
import os  # noqa: E402
srv = start()
os.environ["OLLAMA_BASE_URL"] = f"http://127.0.0.1:{srv.server_port}"

from qagen.ui import pages, state  # noqa: E402
from qagen.ingestion.parsers import parse_requirements  # noqa: E402
from qagen.services.requirement_analyzer import analyze_requirements  # noqa: E402

state.init()
for name, fn in pages.ROUTES.items():          # 1) empty state
    fn()
    print("ok (empty)", name)

sample = here.parent / "data" / "sample_user_stories.md"
st.session_state.requirements = analyze_requirements(parse_requirements(sample.read_bytes(), "s.md"))
st.session_state.source_name = "sample"
st.button.side_effect = lambda label, **k: label in {"Generate test cases", "Analyse requirements"}
pages.generation()                              # 2) real generation through mock Ollama
n = len(st.session_state.cases)
assert n == 25, n
st.button.side_effect = None
st.button.return_value = False
st.toggle.return_value = True
for name, fn in pages.ROUTES.items():          # 3) populated state
    fn()
    print("ok (populated)", name)
print("UI smoke test passed;", n, "cases")
