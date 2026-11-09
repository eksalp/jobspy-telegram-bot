from __future__ import annotations

"""
Paket adapter situs karir.

Dipakai bot.py seperti ini:

    import sites
    specs, jobspy_sites = sites.resolve(["bca", "tiket", "indeed"])
    for spec in specs:
        records = sites.run(spec, query="semua", limit=50, chat_id=chat_id)
"""

from .registry import REGISTRY, SiteSpec, get, names, resolve, run

# import untuk efek samping: mendaftarkan semua situs ke REGISTRY
from . import companies  # noqa: F401,E402

__all__ = ["REGISTRY", "SiteSpec", "get", "names", "resolve", "run", "catalog"]


def catalog() -> str:
    """Ringkasan situs terdaftar, untuk perintah /sites di Telegram."""
    lines = []
    for spec in sorted(REGISTRY.values(), key=lambda s: s.name):
        flags = []
        if spec.verified:
            flags.append("✅")
        else:
            flags.append("⚠️")
        if spec.needs_browser:
            flags.append("🐢")
        lines.append(f"{''.join(flags)} `{spec.name}` — {spec.label}")
    return "\n".join(lines)
