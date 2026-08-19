"""Loads settings from .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_model: str
    fathom_api_key: str
    google_client_secret_path: Path
    google_token_path: Path
    temp_dir: Path


def load_settings() -> Settings:
    return Settings(
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
        fathom_api_key=_require("FATHOM_API_KEY"),
        google_client_secret_path=ROOT_DIR / "credentials" / "client_secret.json",
        google_token_path=ROOT_DIR / "credentials" / "token.json",
        temp_dir=ROOT_DIR / "temp",
    )
