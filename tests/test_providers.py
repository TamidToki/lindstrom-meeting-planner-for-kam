"""Provider adapter tests against a local fake OpenAI-compatible server (no real keys, no network).
This verifies the translation layer and error messages. It does NOT prove a live Gemini/Groq/Azure call works."""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import providers as pv

SEEN = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append(dict(path=self.path, auth=self.headers.get("Authorization"), body=body))
        if "bad401" in self.headers.get("Authorization", ""):
            self.send_response(401); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}}).encode()); return
        has_tool_result = any(m["role"] == "tool" for m in body["messages"])
        if body.get("tools") and not has_tool_result:
            msg = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "kpi", "arguments": json.dumps({"customer": "X", "n": 3})}}]}
        else:
            msg = {"role": "assistant", "content": "OK, utilisation is 80 %."}
        out = {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"], "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(out).encode())


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_port}/v1"
cases = []


def case(n):
    def d(f): cases.append((n, f)); return f
    return d


@case("Tool schema and conversation translate to OpenAI format; the tool call comes back as an Anthropic-style tool_use block")
def _():
    cfg = pv.Config("groq", "key123", "some-model", URL)
    c = pv.get_client(cfg)
    tools = [{"name": "kpi", "description": "d", "input_schema": {"type": "object", "properties": {"customer": {"type": "string"}}}}]
    r = c.messages.create(model="some-model", max_tokens=50, system="SYS", tools=tools, messages=[{"role": "user", "content": "hi"}])
    b = r.content[0]
    sent = SEEN[-1]["body"]
    ok = b.type == "tool_use" and b.name == "kpi" and b.input == {"customer": "X", "n": 3} and sent["tools"][0]["function"]["name"] == "kpi" \
        and sent["messages"][0] == {"role": "system", "content": "SYS"} and SEEN[-1]["auth"] == "Bearer key123"
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": [{"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": b.id, "content": "{\"v\": 80}"}]}]
    r2 = c.messages.create(model="some-model", max_tokens=50, system="SYS", tools=tools, messages=msgs)
    sent2 = SEEN[-1]["body"]["messages"]
    roles = [m["role"] for m in sent2]
    ok2 = r2.content[0].type == "text" and "80 %" in r2.content[0].text and roles == ["system", "user", "assistant", "tool"] and sent2[2]["tool_calls"][0]["id"] == b.id and sent2[3]["tool_call_id"] == b.id
    return ok and ok2, f"tool_use ok={ok}; follow-up roles={roles}"


@case("Test connection: success message; a 401 becomes a plain-language message")
def _():
    ok, msg = pv.test_connection(pv.Config("ollama", "", "m", URL))
    ok2, msg2 = pv.test_connection(pv.Config("groq", "bad401", "m", URL))
    return ok and not ok2 and "rejected the key" in msg2, f"ok: '{msg}' | 401: '{msg2}'"


@case("No key / no model -> not ready -> rules mode (current() is None), with an honest status line")
def _():
    for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "AZURE_OPENAI_API_KEY", "LLM_PROVIDER", "OLLAMA_MODEL"):
        os.environ.pop(k, None)
    return pv.current() is None and "No model configured" in pv.status_line() and pv.get_client() is None, pv.status_line()


@case("Environment: a Gemini key without a model name is not ready; with a model it is; provider inferred")
def _():
    os.environ["GEMINI_API_KEY"] = "g"
    a = pv.current()
    os.environ["GEMINI_MODEL"] = "any-model-name"
    b = pv.current()
    for k in ("GEMINI_API_KEY", "GEMINI_MODEL"):
        os.environ.pop(k)
    return a is None and b is not None and b.provider == "gemini" and b.model == "any-model-name" and "generativelanguage" in b.base_url, f"{b}"


@case("Azure needs endpoint + deployment; Anthropic default model name is only a fallback")
def _():
    c = pv.Config("azure", "k", "", "")
    c2 = pv.Config("azure", "k", "dep", "", "https://x.openai.azure.com")
    a = pv.Config("anthropic", "k", "")
    return not c.ready() and c2.ready() and a.ready(), "azure incomplete/complete; anthropic ready"


@case("DEMO_MODE=1 switches AI off even when a key exists")
def _():
    os.environ["ANTHROPIC_API_KEY"] = "k"
    on = pv.current() is not None
    os.environ["DEMO_MODE"] = "1"
    off = pv.current() is None and "demo mode" in pv.status_line()
    os.environ.pop("DEMO_MODE"); os.environ.pop("ANTHROPIC_API_KEY")
    return on and off, f"with key: {on}; demo: off={off}"


if __name__ == "__main__":
    allok = True
    for i, (n, f) in enumerate(cases, 1):
        try: ok, ev = f()
        except Exception as e:
            import traceback; ok, ev = False, f"EXCEPTION {type(e).__name__}: {e} {traceback.format_exc()[-300:]}"
        allok &= bool(ok); print("PASS" if ok else "FAIL", i, n, "|", ev)
    sys.exit(0 if allok else 1)
