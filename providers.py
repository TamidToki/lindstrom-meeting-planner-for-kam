"""One adapter for the optional LLM: Anthropic, Gemini, Groq, Ollama, Azure OpenAI.

The analyst talks to `client.messages.create(model, max_tokens, system, tools, messages)` (Anthropic shape). For every other provider
this module exposes the same shape on top of an OpenAI-compatible chat API (Gemini, Groq and Ollama all offer one; Azure OpenAI has its own
client), translating tool schemas, tool calls and tool results both ways. Nothing here produces a number: the model only chooses tools and words.

Configuration order: the session (sidebar) > environment variables > Streamlit secrets. Model names are NOT hard-coded: you type the name
your provider shows (suggestions are only placeholders). DEMO_MODE=1 disables AI entirely. No key -> `current()` is None and the app says
"no model configured" and uses rules only."""
from __future__ import annotations
import json, os, uuid
from dataclasses import dataclass, field
from types import SimpleNamespace

PROVIDERS = {
    "anthropic": dict(label="Anthropic (Claude)", key_env="ANTHROPIC_API_KEY", base=None, model_hint="the Claude model name from your Anthropic console", needs_key=True),
    "gemini": dict(label="Google Gemini (free key from AI Studio)", key_env="GEMINI_API_KEY", base="https://generativelanguage.googleapis.com/v1beta/openai/",
                   model_hint="a Gemini model name shown in Google AI Studio", needs_key=True),
    "groq": dict(label="Groq", key_env="GROQ_API_KEY", base="https://api.groq.com/openai/v1", model_hint="a model name from your Groq console", needs_key=True),
    "ollama": dict(label="Ollama (runs on this computer)", key_env="", base="http://localhost:11434/v1", model_hint="a model you have pulled, e.g. the name shown by 'ollama list'", needs_key=False),
    "azure": dict(label="Azure OpenAI (needs an Azure resource and IT)", key_env="AZURE_OPENAI_API_KEY", base=None, model_hint="your Azure deployment name", needs_key=True),
}
ENV_ALIASES = {"gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5-5"       # kept for backwards compatibility; override with ANALYST_MODEL or the sidebar


@dataclass
class Config:
    provider: str = ""
    api_key: str = ""
    model: str = ""
    base_url: str = ""            # ollama / custom OpenAI-compatible endpoint
    endpoint: str = ""            # azure
    api_version: str = "2024-10-21"

    def ready(self) -> bool:
        p = PROVIDERS.get(self.provider)
        if not p or demo_mode():
            return False
        if p["needs_key"] and not self.api_key:
            return False
        if self.provider == "azure":
            return bool(self.endpoint and self.model)
        if self.provider != "anthropic" and not self.model:
            return False
        return True


def demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")


def _secret(name):
    try:
        import streamlit as st
        return st.secrets.get(name)          # raises if no secrets file; handled below
    except Exception:
        return None


def _get(name, default=""):
    return os.getenv(name) or _secret(name) or default


def from_environment() -> Config:
    prov = (_get("LLM_PROVIDER") or "").lower()
    if not prov:                              # infer from whichever key exists; Anthropic first (the original behaviour)
        for p, meta in PROVIDERS.items():
            names = ENV_ALIASES.get(p, (meta["key_env"],))
            if p != "ollama" and any(_get(n) for n in names if n):
                prov = p
                break
        if not prov and _get("OLLAMA_MODEL"):
            prov = "ollama"
    if prov not in PROVIDERS:
        return Config()
    meta = PROVIDERS[prov]
    key = next((_get(n) for n in ENV_ALIASES.get(prov, (meta["key_env"],)) if n and _get(n)), "")
    model = _get("ANALYST_MODEL") or _get(f"{prov.upper()}_MODEL") or (DEFAULT_ANTHROPIC_MODEL if prov == "anthropic" else "")
    return Config(prov, key, model, _get("OLLAMA_BASE_URL", meta["base"] or "") if prov == "ollama" else (meta["base"] or ""),
                  _get("AZURE_OPENAI_ENDPOINT") if prov == "azure" else "", _get("AZURE_OPENAI_API_VERSION", "2024-10-21"))


def session_config() -> Config | None:
    try:
        import streamlit as st
        c = st.session_state.get("_llm_cfg")
        return c if isinstance(c, Config) else None
    except Exception:
        return None


def set_session_config(cfg: Config | None):
    import streamlit as st
    st.session_state["_llm_cfg"] = cfg


def current() -> Config | None:
    """The configuration in force, or None when no usable model is configured (rules mode)."""
    if demo_mode():
        return None
    c = session_config() or from_environment()
    return c if c.ready() else None


def model_name() -> str:
    c = current()
    return c.model if c else (os.getenv("ANALYST_MODEL") or DEFAULT_ANTHROPIC_MODEL)


def status_line() -> str:
    if demo_mode():
        return "AI is switched off in demo mode. Answers come from deterministic rules."
    c = current()
    if c is None:
        return "No model configured. Answers come from deterministic rules and questions the rules cannot answer are declined."
    return f"Model: {PROVIDERS[c.provider]['label']}, {c.model or 'default'}."


# ------------------------------------------------------------------------------------------------ OpenAI-compatible facade
def _tools_to_openai(tools):
    out = []
    for t in tools or []:
        out.append({"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}})
    return out


def _messages_to_openai(system, messages):
    out = [{"role": "system", "content": system}] if system else []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            out.append({"role": m["role"], "content": c})
            continue
        if m["role"] == "assistant":
            text = "".join(b.get("text", "") for b in c if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                     for b in c if b.get("type") == "tool_use"]
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:
            for b in c:
                if b.get("type") == "tool_result":
                    content = b.get("content")
                    if b.get("is_error"):
                        content = "ERROR: " + str(content)
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": content if isinstance(content, str) else json.dumps(content, default=str)})
                elif b.get("type") == "text":
                    out.append({"role": "user", "content": b.get("text", "")})
    return out


def _response_to_blocks(resp):
    msg = resp.choices[0].message
    blocks = []
    if getattr(msg, "content", None):
        blocks.append(SimpleNamespace(type="text", text=msg.content))
    for tc in getattr(msg, "tool_calls", None) or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        blocks.append(SimpleNamespace(type="tool_use", id=tc.id or f"call_{uuid.uuid4().hex[:8]}", name=tc.function.name, input=args))
    return blocks


class _OpenAICompatMessages:
    def __init__(self, client, default_model):
        self._c, self._m = client, default_model

    def create(self, model=None, max_tokens=1000, system=None, tools=None, messages=None, **_):
        kw = dict(model=model or self._m, messages=_messages_to_openai(system, messages or []), max_tokens=max_tokens)
        oa = _tools_to_openai(tools)
        if oa:
            kw["tools"] = oa
        resp = self._c.chat.completions.create(**kw)
        return SimpleNamespace(content=_response_to_blocks(resp), stop_reason="tool_use" if any(b.type == "tool_use" for b in _response_to_blocks(resp)) else "end_turn")


class _Facade:
    def __init__(self, client, model):
        self.messages = _OpenAICompatMessages(client, model)


def get_client(cfg: Config | None = None):
    """-> an object with .messages.create(...) in Anthropic shape, or None (rules mode)."""
    cfg = cfg or current()
    if cfg is None or not cfg.ready():
        return None
    try:
        if cfg.provider == "anthropic":
            import anthropic
            return anthropic.Anthropic(api_key=cfg.api_key)
        import openai
        if cfg.provider == "azure":
            return _Facade(openai.AzureOpenAI(api_key=cfg.api_key, azure_endpoint=cfg.endpoint, api_version=cfg.api_version), cfg.model)
        return _Facade(openai.OpenAI(api_key=cfg.api_key or "not-needed", base_url=cfg.base_url or PROVIDERS[cfg.provider]["base"]), cfg.model)
    except Exception:
        return None


def complete_text(prompt: str, max_tokens=300, cfg: Config | None = None) -> str | None:
    """One short plain completion for wording tasks (no tools). None when no model is configured or the call fails."""
    c = get_client(cfg)
    if c is None:
        return None
    try:
        r = c.messages.create(model=(cfg or current()).model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        return "".join(getattr(b, "text", "") for b in r.content if getattr(b, "type", "") == "text").strip() or None
    except Exception:
        return None


def friendly_error(e: Exception) -> str:
    n, s = type(e).__name__, str(e)
    low = s.lower()
    if "401" in low or "403" in low or "api key" in low and ("invalid" in low or "not valid" in low) or "unauthorized" in low or "authentication" in n.lower():
        return "The provider rejected the key. Check that you copied the whole key and that it belongs to this provider."
    if "404" in low or "not found" in low or "does not exist" in low:
        return "The provider does not know that model name. Copy the exact model name from the provider's console."
    if "429" in low or "quota" in low or "rate" in low and "limit" in low:
        return "The provider says the free quota or rate limit is used up. Wait a bit, or use another key."
    if "connect" in low or "timed out" in low or "timeout" in low or "resolve" in low or "refused" in low:
        return "Could not reach the provider. Check the internet connection (or that Ollama is running on this computer)."
    if "no module named" in low:
        return "A software package is missing on this computer: run 'pip install -r requirements.txt'."
    return f"The provider returned an error ({n}). Details: {s[:160]}"


def test_connection(cfg: Config) -> tuple[bool, str]:
    if demo_mode():
        return False, "AI is switched off in demo mode."
    if not cfg.ready():
        need = "an API key" if PROVIDERS.get(cfg.provider, {}).get("needs_key") and not cfg.api_key else "a model name" if not cfg.model else "the endpoint"
        return False, f"Not ready: still needs {need}."
    try:
        c = get_client(cfg)
        if c is None:
            return False, "Could not set up the connection (is the 'openai' package installed? run pip install -r requirements.txt)."
        r = c.messages.create(model=cfg.model, max_tokens=20, messages=[{"role": "user", "content": "Reply with the single word OK."}])
        txt = "".join(getattr(b, "text", "") for b in r.content if getattr(b, "type", "") == "text").strip()
        return True, f"Connected. The model replied: {txt[:40] or '(empty reply)'}"
    except Exception as e:
        return False, friendly_error(e)
