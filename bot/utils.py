from __future__ import annotations

import textwrap
from typing import Iterable, Sequence


def format_bold(text: str) -> str:
    return f"<b>{escape(text)}</b>"


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def bullet_list(items: Sequence[str]) -> str:
    return "\n".join(f"• {escape(item)}" for item in items)


def chunk_text(text: str, limit: int = 3500) -> Iterable[str]:
    text = textwrap.dedent(text).strip()
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        yield text[:split_at].strip()
        text = text[split_at:].lstrip()
    if text:
        yield text
