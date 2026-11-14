"""Optional drafted answers: a forced-tool Anthropic call, verified against the cited passages.
Inactive without a key. Only verified answers are ever cached or returned."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from secanalyst.answer.verify import verify_answer
from secanalyst.config import REPO_ROOT, load_settings

PROMPT_VERSION = "answer_v1"
PROMPT_FILE = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md"
CACHE_DIR = REPO_ROOT / "data" / "ai_cache"
USAGE_PATH = REPO_ROOT / "data" / ".llm_usage.json"
TOOL_NAME = "write_answer"
MAX_TOKENS = 1500
_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "Answer using only the passages."},
        "citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Chunk ids of the passages the answer relies on.",
        },
    },
    "required": ["answer", "citations"],
}


@dataclass(frozen=True)
class DraftAnswer:
    answer: str
    citations: list[str]


class LLMClient(Protocol):
    def write_answer(self, prompt: str) -> dict:
        """Return ``{"answer": str, "citations": [chunk_id, ...]}``."""
        ...


def get_api_key() -> str | None:
    """ANTHROPIC_API_KEY from the environment, else Streamlit secrets (Cloud)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        import streamlit as st

        return st.secrets.get("ANTHROPIC_API_KEY") or None
    except Exception:  # noqa: BLE001 - no streamlit / no secrets file
        return None


class AnthropicClient:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        key = api_key or get_api_key()
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set; cannot call the Anthropic API")
        import anthropic

        self._client = anthropic.Anthropic(api_key=key)
        self._model = model or load_settings().llm_model

    def write_answer(self, prompt: str) -> dict:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            tools=[{"name": TOOL_NAME, "description": "Write the cited answer.",
                    "input_schema": _SCHEMA}],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )  # fmt: skip
        if getattr(resp, "stop_reason", None) == "max_tokens":
            raise RuntimeError("Anthropic response hit max_tokens; the answer was discarded")
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                data = dict(block.input)
                if not isinstance(data.get("answer"), str) or not isinstance(
                    data.get("citations"), list
                ):
                    raise RuntimeError("write_answer returned no answer/citations")
                return data
        raise RuntimeError("Anthropic response contained no tool_use block")


def build_prompt(question: str, hits) -> str:
    passages = "\n\n".join(f'<passage id="{h.chunk_id}">\n{h.text}\n</passage>' for h in hits)
    tpl = PROMPT_FILE.read_text(encoding="utf-8")
    return tpl.replace("{passages}", passages).replace("{question}", question)


def cache_key(question: str, hits) -> str:
    raw = question + "|" + ",".join(h.chunk_id for h in hits) + "|" + PROMPT_VERSION
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def calls_today(usage_path: Path = USAGE_PATH) -> int:
    try:
        d = json.loads(Path(usage_path).read_text(encoding="utf-8"))
        return int(d["count"]) if d.get("date") == date.today().isoformat() else 0
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def _bump(usage_path: Path) -> None:
    usage_path = Path(usage_path)
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(
        json.dumps({"date": date.today().isoformat(), "count": calls_today(usage_path) + 1}),
        encoding="utf-8",
    )


def answer_cached(
    question: str,
    hits,
    client: LLMClient | None = None,
    refresh: bool = False,
    cache_dir: Path = CACHE_DIR,
    usage_path: Path = USAGE_PATH,
    cap: int | None = None,
) -> DraftAnswer | None:
    """A verified answer from the cache, else (if a client is given and today's cap allows) a
    live one: one retry on failed verification, then None. Unverified text is never kept."""
    if not hits:
        return None
    path = Path(cache_dir) / f"{cache_key(question, hits)}.json"
    if path.exists() and not refresh:
        try:
            d = DraftAnswer(**json.loads(path.read_text(encoding="utf-8")))
            if not verify_answer(d, hits):
                return d
        except (OSError, ValueError, TypeError):
            pass
    if client is None:
        return None
    cap = load_settings().daily_llm_cap if cap is None else cap
    prompt = build_prompt(question, hits)
    for _ in range(2):
        if calls_today(usage_path) >= cap:
            return None
        _bump(usage_path)
        try:
            raw = client.write_answer(prompt)
            d = DraftAnswer(str(raw["answer"]), [str(c) for c in raw["citations"]])
        except Exception:  # noqa: BLE001, S112 - API/format error counts as a failed attempt
            continue
        if not verify_answer(d, hits):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(d), indent=1), encoding="utf-8")
            return d
    return None
