from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BOT_TOKEN = (
    "8567935515:AAHwNAtuag78cB6_9Mg3vz8EZe14AG7CI6A"
    if os.getenv("ALLOW_INLINE_TOKEN", "0") == "1"
    else None
)


@dataclass(frozen=True, slots=True)
class BotSettings:
    bot_token: str
    admin_ids: tuple[int, ...]
    database_path: Path
    bot_details_path: Path
    request_timeout: float = 12.0


def load_settings() -> BotSettings:
    token = os.getenv("TELEGRAM_BOT_TOKEN") or DEFAULT_BOT_TOKEN
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN environment variable is required. "
            "Set ALLOW_INLINE_TOKEN=1 to use the embedded token."
        )

    admin_ids_env = os.getenv("TELEGRAM_ADMIN_IDS", "")
    admin_ids: list[int] = []

    if admin_ids_env.strip():
        for value in admin_ids_env.replace(",", " ").split():
            try:
                admin_ids.append(int(value))
            except ValueError:
                continue

    admin_ids.append(8149429097)
    admin_ids = sorted(set(admin_ids))

    base_path = Path(os.getenv("BOT_DATA_DIR", ".")).resolve()
    base_path.mkdir(parents=True, exist_ok=True)

    database_path = base_path / "bot_data.sqlite3"
    bot_details_path = base_path / "bot_details.txt"

    return BotSettings(
        bot_token=token,
        admin_ids=tuple(admin_ids),
        database_path=database_path,
        bot_details_path=bot_details_path,
    )
