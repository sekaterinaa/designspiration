"""Runtime configuration, loaded from the environment (and an optional .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional convenience dependency
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False


@dataclass(frozen=True)
class Config:
    telegram_token: str
    anthropic_api_key: str
    model: str = "claude-opus-5"
    db_path: Path = Path("pnl.db")
    default_currency: str = "USD"
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)

    def is_allowed(self, user_id: int) -> bool:
        return not self.allowed_user_ids or user_id in self.allowed_user_ids


class ConfigError(RuntimeError):
    """Raised when required settings are missing."""


def _parse_user_ids(raw: str) -> frozenset[int]:
    ids = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"ALLOWED_USER_IDS contains a non-numeric entry: {chunk!r}") from exc
    return frozenset(ids)


def load_config(env_file: str | os.PathLike[str] | None = ".env") -> Config:
    if env_file and Path(env_file).exists():
        load_dotenv(env_file)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ConfigError(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and put the "
            "token in your .env file (see .env.example)."
        )

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "ANTHROPIC_API_KEY is not set. The bot needs it to read trades out of "
            "screenshots (see .env.example)."
        )

    return Config(
        telegram_token=token,
        anthropic_api_key=api_key,
        model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5").strip() or "claude-opus-5",
        db_path=Path(os.getenv("PNL_DB_PATH", "pnl.db").strip() or "pnl.db"),
        default_currency=(os.getenv("DEFAULT_CURRENCY", "USD").strip() or "USD").upper(),
        allowed_user_ids=_parse_user_ids(os.getenv("ALLOWED_USER_IDS", "")),
    )
