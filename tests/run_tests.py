"""Dependency-free runner: python tests/run_tests.py  (pytest also works: pytest -q)"""
import importlib, sys, traceback
from pathlib import Path

here = Path(__file__).resolve().parent
sys.path[:0] = [str(here), str(here.parent / "src")]
failed = total = 0
for mod_name in ("test_validators", "test_pipeline"):
    mod = importlib.import_module(mod_name)
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        total += 1
        try:
            getattr(mod, name)()
            print(f"PASS {mod_name}.{name}")
        except Exception:
            failed += 1
            print(f"FAIL {mod_name}.{name}")
            traceback.print_exc()
print(f"\n{total - failed}/{total} passed")
sys.exit(1 if failed else 0)
