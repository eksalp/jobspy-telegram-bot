from __future__ import annotations

import requests

import config

API_BASE = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def send_message(chat_id: int | str, text: str, parse_mode: str | None = "Markdown") -> dict:
    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def edit_message(
    chat_id: int | str, message_id: int, text: str, parse_mode: str | None = "Markdown"
) -> dict:
    resp = requests.post(
        f"{API_BASE}/editMessageText",
        json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
