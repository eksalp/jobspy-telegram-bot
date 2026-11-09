from __future__ import annotations

"""
Perintah /hapusdata untuk membersihkan tabel jobs lewat Telegram.

DEFAULT-NYA AMAN: menghapus lowongan yang sudah lama tidak ter-update
(bukan truncate total). Alasannya sudah dibahas panjang — truncate total
tiap minggu akan merusak checkpoint MagangHub (yang butuh berminggu-minggu
untuk menyelesaikan satu putaran penuh 1256 halaman) dan bikin Jobly
menampilkan database kosong selama scraping ulang berlangsung.

Cara kerja "hapus yang basi": upsert sudah membuat updated_at ter-refresh
tiap kali lowongan yang SAMA di-scrape ulang. Lowongan yang sudah hilang
dari situs sumber (ditutup/expired) tidak pernah tersentuh lagi -- jadi
updated_at-nya makin lama makin basi. Itu sinyal alami "lowongan ini
kemungkinan sudah tidak aktif", tanpa perlu hapus-total.

PEMAKAIAN

    /hapusdata            hapus yang lebih basi dari 10 hari (default)
    /hapusdata 3          hapus yang lebih basi dari 3 hari
    /hapusdata semua      TRUNCATE TOTAL — hapus SEMUA baris, konfirmasi 2x

Semua varian menampilkan dulu BERAPA baris yang akan terhapus dan minta
konfirmasi tombol sebelum benar-benar mengeksekusi -- tidak ada yang
langsung jalan tanpa jeda, karena ini operasi yang tidak bisa dibatalkan.

PASANG KE bot.py

    import hapusdata
    hapusdata.register(app, is_allowed, escape_md)

Taruh di dalam main(), sebaris dengan pendaftaran site_commands yang sudah
ada.
"""

import logging
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logger = logging.getLogger(__name__)

DEFAULT_HARI_BASI = 10

# Menyimpan rencana penghapusan sambil menunggu konfirmasi tombol, supaya
# tidak perlu menyimpan query di callback_data (yang dibatasi 64 byte oleh
# Telegram). Kunci = token acak per permintaan, dibuang setelah dipakai atau
# kedaluwarsa satu jam.
_RENCANA: dict[str, dict] = {}


def _buang_rencana_lama() -> None:
    import time

    batas = time.time() - 3600
    kadaluwarsa = [k for k, v in _RENCANA.items() if v["dibuat"] < batas]
    for k in kadaluwarsa:
        _RENCANA.pop(k, None)


async def hapusdata_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    is_allowed = context.bot_data["is_allowed"]
    escape_md = context.bot_data["escape_md"]

    if not is_allowed(chat_id):
        await update.message.reply_text("Maaf, kamu tidak punya akses ke bot ini.")
        return

    import db

    argumen = (context.args or [])
    mode_semua = bool(argumen) and argumen[0].strip().lower() == "semua"

    if mode_semua:
        # TRUNCATE TOTAL. Paling destruktif, jadi butuh peringatan paling
        # jelas -- termasuk pengingat eksplisit soal MagangHub, supaya
        # keputusan ini diambil sadar, bukan kebiasaan tiap minggu tanpa
        # dipikir ulang.
        try:
            total = await _hitung_total(db)
        except Exception as e:  # noqa: BLE001
            logger.exception("Gagal menghitung total baris")
            await update.message.reply_text(f"Gagal menghitung data: {escape_md(e)}")
            return

        token = str(uuid.uuid4())[:8]
        _buang_rencana_lama()
        _RENCANA[token] = {"mode": "semua", "hari": None, "dibuat": _sekarang()}

        total_teks = escape_md(f"{total:,}")
        teks = (
            f"⚠️ *HAPUS SEMUA DATA*\n\n"
            f"Ini akan menghapus *{total_teks} baris* — seluruh isi tabel, "
            f"bukan cuma yang basi.\n\n"
            f"Ingat: checkpoint MagangHub tidak akan otomatis reset. "
            f"Kalau kamu mau MagangHub mulai dari halaman 1 lagi juga, "
            f"jalankan manual setelah ini:\n"
            f"`python -c \"from maganghub import reset_checkpoint; "
            f"reset_checkpoint()\"`\n\n"
            f"Yakin mau lanjut?"
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Ya, hapus semua", callback_data=f"hapusdata:{token}"),
            InlineKeyboardButton("Batal", callback_data=f"hapusdata_batal:{token}"),
        ]])
        await update.message.reply_text(
            teks, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        return

    # Mode default: hapus yang basi.
    try:
        hari = int(argumen[0]) if argumen else DEFAULT_HARI_BASI
        if hari < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Format: /hapusdata [jumlah_hari]\n"
            "Contoh: /hapusdata 10  (hapus yang basi lebih dari 10 hari)\n"
            "atau: /hapusdata semua  (hapus semua, dengan konfirmasi)"
        )
        return

    try:
        total = await _hitung_basi(db, hari)
    except Exception as e:  # noqa: BLE001
        logger.exception("Gagal menghitung data basi")
        await update.message.reply_text(f"Gagal menghitung data: {escape_md(e)}")
        return

    if total == 0:
        await update.message.reply_text(
            f"Tidak ada lowongan yang lebih basi dari {hari} hari. "
            "Tidak ada yang perlu dihapus."
        )
        return

    token = str(uuid.uuid4())[:8]
    _buang_rencana_lama()
    _RENCANA[token] = {"mode": "basi", "hari": hari, "dibuat": _sekarang()}

    total_teks = escape_md(f"{total:,}")
    teks = (
        f"🧹 *{total_teks} lowongan* belum ter-update lagi lebih dari "
        f"*{hari} hari* (kemungkinan sudah ditutup di situs asalnya).\n\n"
        f"Hapus baris-baris itu?"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🧹 Ya, hapus", callback_data=f"hapusdata:{token}"),
        InlineKeyboardButton("Batal", callback_data=f"hapusdata_batal:{token}"),
    ]])
    await update.message.reply_text(
        teks, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def hapusdata_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = str(query.message.chat_id)
    is_allowed = context.bot_data["is_allowed"]

    if not is_allowed(chat_id):
        await query.answer("Tidak punya akses.", show_alert=True)
        return

    aksi, token = query.data.split(":", 1)
    rencana = _RENCANA.pop(token, None)

    if rencana is None:
        await query.answer()
        await query.edit_message_text("Permintaan sudah kedaluwarsa, jalankan /hapusdata lagi.")
        return

    if aksi == "hapusdata_batal":
        await query.answer("Dibatalkan.")
        await query.edit_message_text("Dibatalkan, tidak ada yang dihapus.")
        return

    await query.answer("Menghapus...")

    import db

    escape_md = context.bot_data["escape_md"]
    try:
        if rencana["mode"] == "semua":
            jumlah = await _eksekusi_hapus_semua(db)
            await query.edit_message_text(
                f"✅ Selesai. {jumlah:,} baris dihapus, tabel dikosongkan total."
            )
        else:
            jumlah = await _eksekusi_hapus_basi(db, rencana["hari"])
            await query.edit_message_text(
                f"✅ Selesai. {jumlah:,} lowongan basi (>{rencana['hari']} hari) dihapus."
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("Gagal menghapus data")
        await query.edit_message_text(f"❌ Gagal menghapus: {escape_md(e)}")


# --------------------------------------------------------------------------- #
# Query database. Dijalankan di thread terpisah (asyncio.to_thread) supaya
# tidak memblokir event loop bot -- pola yang sama dipakai handler lain.
# --------------------------------------------------------------------------- #
def _sekarang() -> float:
    import time
    return time.time()


async def _hitung_total(db) -> int:
    import asyncio

    def _query():
        client = db.get_client()
        resp = client.table("jobs").select("id", count="exact").limit(1).execute()
        return resp.count or 0

    return await asyncio.to_thread(_query)


async def _hitung_basi(db, hari: int) -> int:
    import asyncio

    def _query():
        from datetime import datetime, timedelta, timezone
        batas = (datetime.now(timezone.utc) - timedelta(days=hari)).isoformat()
        client = db.get_client()
        resp = (
            client.table("jobs")
            .select("id", count="exact")
            .lt("updated_at", batas)
            .limit(1)
            .execute()
        )
        return resp.count or 0

    return await asyncio.to_thread(_query)


async def _eksekusi_hapus_basi(db, hari: int) -> int:
    import asyncio

    def _query():
        from datetime import datetime, timedelta, timezone
        batas = (datetime.now(timezone.utc) - timedelta(days=hari)).isoformat()
        client = db.get_client()
        resp = client.table("jobs").delete().lt("updated_at", batas).execute()
        return len(resp.data or [])

    return await asyncio.to_thread(_query)


async def _eksekusi_hapus_semua(db) -> int:
    import asyncio

    def _query():
        client = db.get_client()
        # .neq("id", 0) dipakai karena postgrest mewajibkan filter WHERE
        # eksplisit untuk delete -- id selalu > 0, jadi ini efektif "semua".
        resp = client.table("jobs").delete().neq("id", 0).execute()
        return len(resp.data or [])

    return await asyncio.to_thread(_query)


def register(app: Application, is_allowed, escape_md) -> None:
    """Daftarkan /hapusdata ke bot. Panggil dari bot.py:

        import hapusdata
        hapusdata.register(app, is_allowed, escape_md)
    """
    app.bot_data["is_allowed"] = is_allowed
    app.bot_data["escape_md"] = escape_md

    app.add_handler(CommandHandler("hapusdata", hapusdata_cmd))
    app.add_handler(CallbackQueryHandler(hapusdata_callback, pattern=r"^hapusdata"))

    logger.info("Perintah /hapusdata terdaftar")
