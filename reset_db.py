from __future__ import annotations

"""
Perintah /reset: kosongkan SELURUH tabel `jobs` dari Telegram, setara dengan

    TRUNCATE TABLE jobs RESTART IDENTITY;

di SQL Editor Supabase -- instan berapa pun jumlah barisnya, dan nomor `id`
mulai lagi dari 1. Berbeda dengan `/hapusdata semua` yang memakai DELETE
lewat REST dan kena statement timeout untuk tabel besar.

API REST Supabase tidak bisa menjalankan TRUNCATE langsung, jadi perintahnya
disimpan sebagai fungsi Postgres `reset_jobs()` yang dipanggil lewat RPC.
Fungsi itu harus dibuat SEKALI di SQL Editor -- lihat reset_jobs.sql.

Keamanan: fungsi hanya boleh dieksekusi role `service_role` (kunci yang
dipakai bot). Role `anon` -- kunci publik yang dipakai Jobly di browser --
SENGAJA dicabut aksesnya, supaya pengunjung situs tidak bisa memanggil
fungsi ini untuk menghapus data.

Alur: /reset -> bot menampilkan jumlah baris + tombol konfirmasi ->
"Ya, kosongkan" -> TRUNCATE. Tombol kedaluwarsa setelah 5 menit.

PASANG KE bot.py (di dalam main(), di sebelah hapusdata.register):

    import reset_db
    reset_db.register(app, is_allowed, escape_md)
"""

import asyncio
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)

BERLAKU_DETIK = 300
_KUNCI = "reset_db_diminta"


def _hitung() -> int:
    import db
    resp = db.get_client().table("jobs").select("id", count="exact").limit(1).execute()
    return resp.count or 0


def _kosongkan() -> None:
    import db
    db.get_client().rpc("reset_jobs").execute()


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_allowed = context.bot_data["reset_is_allowed"]
    if not is_allowed(update.effective_chat.id):
        await update.message.reply_text("Maaf, kamu tidak punya akses ke bot ini.")
        return

    try:
        jumlah = await asyncio.to_thread(_hitung)
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(f"❌ Gagal membaca jumlah data: {e}")
        return

    context.chat_data[_KUNCI] = time.time()
    tombol = InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑 Ya, kosongkan", callback_data="rs:ya"),
        InlineKeyboardButton("Batal", callback_data="rs:batal"),
    ]])
    await update.message.reply_text(
        f"⚠️ *Kosongkan seluruh tabel jobs?*\n\n"
        f"{jumlah:,} lowongan akan dihapus *permanen* dan tidak bisa "
        f"dikembalikan. Setelah itu jalankan /updateall untuk scrape ulang.\n\n"
        f"Tombol ini berlaku {BERLAKU_DETIK // 60} menit.",
        parse_mode=ParseMode.MARKDOWN, reply_markup=tombol)


async def reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    is_allowed = context.bot_data["reset_is_allowed"]
    if not is_allowed(query.message.chat_id):
        await query.answer("Tidak punya akses.", show_alert=True)
        return

    diminta = context.chat_data.pop(_KUNCI, None)
    if query.data == "rs:batal":
        await query.answer()
        await query.edit_message_text("Dibatalkan. Data tidak diubah.")
        return
    if not diminta or time.time() - diminta > BERLAKU_DETIK:
        await query.answer("Kedaluwarsa. Kirim /reset lagi.", show_alert=True)
        await query.edit_message_text("Konfirmasi kedaluwarsa. Data tidak diubah.")
        return

    await query.answer()
    await query.edit_message_text("⏳ Mengosongkan tabel jobs...")
    try:
        await asyncio.to_thread(_kosongkan)
    except Exception as e:  # noqa: BLE001
        logger.exception("reset_jobs gagal")
        pesan = str(e)
        if "reset_jobs" in pesan and ("not find" in pesan or "PGRST202" in pesan
                                       or "does not exist" in pesan):
            pesan = ("Fungsi reset_jobs() belum dibuat di Supabase. Jalankan "
                     "isi file reset_jobs.sql sekali di SQL Editor.")
        await query.edit_message_text(f"❌ Gagal: {pesan}")
        return

    try:
        sisa = await asyncio.to_thread(_hitung)
    except Exception:  # noqa: BLE001
        sisa = "?"
    await query.edit_message_text(
        f"✅ Tabel jobs sudah kosong (sisa: {sisa} baris).\n"
        f"Kirim /updateall untuk scrape ulang semua situs.")


def register(app: Application, is_allowed, escape_md) -> None:
    app.bot_data["reset_is_allowed"] = is_allowed
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CallbackQueryHandler(reset_callback, pattern=r"^rs:"))
    logger.info("Perintah /reset terdaftar")
