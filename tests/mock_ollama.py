"""Tiny fake Ollama server so the pipeline can be tested without a model."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def _cases(req_id: str) -> dict:
    base = lambda **k: {**dict(preconditions="User is on the page", steps=["Open the page", "Perform the action", "Observe the result"],  # noqa: E731
                               priority="High", automation="Yes", covers_criterion=""), **k}
    return {"test_cases": [
        base(scenario=f"{req_id} valid input accepted", description="Happy path", test_data="valid values",
             expected_result="The action completes and the success confirmation is displayed", test_type="Positive",
             covers_criterion="Successful login redirects the user to the dashboard"),
        base(scenario=f"{req_id} invalid input rejected", description="Negative path", test_data="invalid values",
             expected_result="A generic error message is shown and no session is created", test_type="Negative",
             covers_criterion="An invalid email or password shows a generic error message"),
        base(scenario=f"{req_id} boundary at maximum", description="Upper boundary", test_data="max value",
             expected_result="The maximum allowed value is accepted without error", test_type="Boundary", priority="Medium"),
        base(scenario=f"{req_id} injection attempt", description="SQL injection in input", test_data="' OR 1=1 --",
             expected_result="The input is rejected and sanitised; no data is leaked", test_type="Security"),
        # exact duplicate of the first -> must be removed by dedup
        base(scenario=f"{req_id} valid input accepted", description="Happy path", test_data="valid values",
             expected_result="The action completes and the success confirmation is displayed", test_type="Positive"),
        # vague expected result -> must be flagged by validators
        base(scenario=f"{req_id} empty field", description="Empty mandatory field", test_data="",
             expected_result="works", test_type="Validation", priority="Low"),
    ]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": "qwen2.5:3b"}]})
        else:
            self._send({}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n))
        user = req["messages"][-1]["content"]
        rid = (re.search(r"Requirement ID:\s*(\S+)", user) or [None, "REQ-X"])[1]
        if "Generate up to" in user:
            payload = _cases(rid)
        elif "Test scenario:" in user:
            payload = {"valid": ["alice@example.com"], "invalid": ["not-an-email"], "boundary": [], "notes": "mock"}
        else:
            payload = {"kind": "Functional", "nfr_category": "", "acceptance_criteria": ["[derived] Contact details are saved"],
                       "missing_criteria": ["Validation rules for phone number format"]}
        # emulate Qwen3 leaking a think block to test the stripper
        content = "<think>reasoning</think>" + json.dumps(payload)
        self._send({
            "message": {"role": "assistant", "content": content},
            "prompt_eval_count": 11,
            "eval_count": 7,
        })


def start(port=0):
    srv = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
