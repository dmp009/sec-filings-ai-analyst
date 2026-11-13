"""Typed loaders for the YAML files under config/. Paths resolve from REPO_ROOT, not cwd."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"


class Company(BaseModel):
    ticker: str
    name: str
    cik: str
    fy_end_month: int


class Settings(BaseModel):
    llm_model: str
    as_of: date | None = None
    chunk_words: int = 320
    chunk_overlap: int = 60
    top_k: int = 8
    score_floor: float
    daily_llm_cap: int = 50
    user_agent_default: str
    disclaimer: str


def _read(name: str):
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_companies() -> list[Company]:
    return [Company(**c) for c in _read("companies.yaml")["companies"]]


def load_settings() -> Settings:
    return Settings(**_read("settings.yaml"))


def load_red_flags() -> dict[str, dict[str, list[str]]]:
    return _read("red_flags.yaml")


def load_questions() -> list[dict]:
    return _read("questions.yaml")["questions"]


def load_xbrl_tags() -> dict[str, list[str]]:
    return _read("xbrl_tags.yaml")
