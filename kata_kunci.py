from __future__ import annotations

"""
Perintah /carikerja: jalankan daftar kata kunci siap pakai ke Indeed &
LinkedIn (lewat JobSpy) dengan sekali klik, tanpa mengetik /update panjang.

PEMAKAIAN

    /carikerja              tampilkan tombol kelompok bidang
    /carikerja semua        langsung jalankan SEMUA kelompok
    /carikerja teknologi    langsung jalankan satu kelompok (pakai kuncinya)

Prosesnya berjalan di LATAR BELAKANG, jadi bot tetap bisa menerima perintah
lain selama pencarian berlangsung. Kata kunci diproses SATU PER SATU
(berurutan) dan hasilnya disimpan ke Supabase setiap satu kata kunci
selesai -- kalau proses berhenti di tengah, hasil yang sudah didapat tetap
aman. Ada tombol "Berhenti" di pesan progres; berhentinya setelah kata
kunci yang sedang berjalan selesai.

Hanya satu proses /carikerja yang boleh berjalan dalam satu waktu, supaya
LinkedIn/Indeed tidak dibanjiri request paralel (LinkedIn cepat membalas
HTTP 429 kalau terlalu banyak).

Mengubah daftar kata kunci cukup di KELOMPOK di bawah.

PASANG KE bot.py (di dalam main(), di sebelah hapusdata.register):

    import kata_kunci
    kata_kunci.register(app, is_allowed, escape_md)
"""

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logger = logging.getLogger(__name__)

SITUS = ["indeed", "linkedin"]
HASIL_PER_KATA = 500  # Indeed/LinkedIn membatasi hasil per pencarian; lebih besar tidak menambah.

# kunci -> (label tombol, daftar kata kunci)
KELOMPOK: dict[str, tuple[str, list[str]]] = {
    "teknologi": ("💻 Teknologi", [
        "data analyst", "backend engineer", "frontend developer",
        "fullstack developer", "mobile developer", "android developer",
        "ios developer", "devops engineer", "qa engineer", "data engineer",
    ]),
    "data_produk": ("🧠 Data & Produk", [
        "data scientist", "machine learning engineer", "business intelligence",
        "ui ux designer", "product manager", "it support", "network engineer",
        "cyber security",
    ]),
    "keuangan": ("💰 Keuangan & Admin", [
        "accounting", "akuntan", "finance staff", "tax", "auditor", "admin",
        "staff administrasi", "sekretaris",
    ]),
    "pemasaran": ("📣 Pemasaran & Penjualan", [
        "digital marketing", "sales executive", "marketing", "content creator",
        "social media specialist", "brand manager", "account executive",
        "business development", "telemarketing", "sales marketing",
    ]),
    "sdm_ops": ("🏭 SDM, Operasional, Logistik", [
        "hr generalist", "recruiter", "talent acquisition", "operations",
        "supply chain", "procurement", "warehouse", "logistik",
    ]),
    "teknik": ("🔧 Layanan & Teknik", [
        "customer service", "customer success", "teknisi", "mechanical engineer",
        "civil engineer", "electrical engineer", "quality control",
        "project manager",
    ]),
    "lainnya": ("🧩 Profesi Lain", [
        "guru", "perawat", "apoteker", "graphic designer", "copywriter",
        "legal", "driver", "kasir",
    ]),
    "pemula": ("🎓 Pemula & Fleksibel", [
        "management trainee", "fresh graduate", "magang", "internship",
        "part time", "remote", "freelance", "kerja dari rumah",
    ]),
}

_KUNCI_STATE = "kata_kunci_state"


def _state(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.application.bot_data.setdefault(
        _KUNCI_STATE, {"berjalan": False, "berhenti": False})


def _keyboard() -> InlineKeyboardMarkup:
    tombol = [
        [InlineKeyboardButton(f"{label} ({len(kata)})", callback_data=f"kk:{kunci}")]
        for kunci, (label, kata) in KELOMPOK.items()
    ]
    total = sum(len(k) for _, k in KELOMPOK.values())
    tombol.append([InlineKeyboardButton(
        f"🚀 Semua kelompok ({total} kata kunci)", callback_data="kk:semua")])
    return InlineKeyboardMarkup(tombol)


def _daftar_kata(pilihan: str) -> list[str]:
    if pilihan == "semua":
        hasil: list[str] = []
        for _, kata in KELOMPOK.values():
            hasil.extend(k for k in kata if k not in hasil)
        return hasil
    return list(KELOMPOK[pilihan][1])


async def carikerja_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_allowed = context.bot_data["is_allowed"]
    if not is_allowed(update.effective_chat.id):
        await update.message.reply_text("Maaf, kamu tidak punya akses ke bot ini.")
        return

    arg = (context.args[0].strip().lower() if context.args else "")
    if arg:
        if arg != "semua" and arg not in KELOMPOK:
            await update.message.reply_text(
                "Kelompok tidak dikenal. Pilihan: semua, " + ", ".join(KELOMPOK))
            return
        await _mulai(update.effective_chat.id, arg, context)
        return

    await update.message.reply_text(
        "Pilih kelompok kata kunci yang mau dicari di Indeed & LinkedIn:",
        reply_markup=_keyboard(),
    )


async def carikerja_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    is_allowed = context.bot_data["is_allowed"]
    if not is_allowed(query.message.chat_id):
        await query.answer("Tidak punya akses.", show_alert=True)
        return

    pilihan = query.data.split(":", 1)[1]

    if pilihan == "stop":
        st = _state(context)
        if st["berjalan"]:
            st["berhenti"] = True
            await query.answer("Akan berhenti setelah kata kunci ini selesai.")
        else:
            await query.answer("Tidak ada pencarian yang berjalan.")
        return

    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await _mulai(query.message.chat_id, pilihan, context)


async def _mulai(chat_id: int, pilihan: str, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = _state(context)
    if st["berjalan"]:
        await context.bot.send_message(
            chat_id, "⏳ Masih ada pencarian /carikerja yang berjalan. "
                     "Tunggu selesai, atau tekan tombol Berhenti di pesan progresnya.")
        return

    kata = _daftar_kata(pilihan)
    st["berjalan"], st["berhenti"] = True, False
    # Dijalankan di latar belakang supaya bot tetap responsif selama
    # pencarian yang bisa makan waktu puluhan menit.
    context.application.create_task(_jalankan(chat_id, pilihan, kata, context))


async def _jalankan(chat_id: int, pilihan: str, kata: list[str],
                    context: ContextTypes.DEFAULT_TYPE) -> None:
    import config
    import db
    from scraper import df_to_records, run_search

    escape_md = context.bot_data["escape_md"]
    st = _state(context)
    tombol_stop = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏹ Berhenti", callback_data="kk:stop")]])
    judul = "Semua kelompok" if pilihan == "semua" else KELOMPOK[pilihan][0]

    status = await context.bot.send_message(
        chat_id, f"🔍 Mulai *{escape_md(judul)}*: {len(kata)} kata kunci "
                 f"({', '.join(SITUS)})...",
        parse_mode=ParseMode.MARKDOWN, reply_markup=tombol_stop)

    ringkasan: list[str] = []
    total_simpan = 0
    try:
        for i, term in enumerate(kata, start=1):
            if st["berhenti"]:
                ringkasan.append(f"⏹ dihentikan sebelum \"{term}\"")
                break
            try:
                await status.edit_text(
                    f"🔍 ({i}/{len(kata)}) *{escape_md(term)}*\n"
                    f"Tersimpan sejauh ini: {total_simpan}",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=tombol_stop)
            except Exception:  # noqa: BLE001
                pass

            try:
                df = await asyncio.to_thread(
                    run_search, search_term=term,
                    location=config.DEFAULT_LOCATION, sites=SITUS,
                    country_indeed=config.DEFAULT_COUNTRY_INDEED,
                    results_wanted=HASIL_PER_KATA,
                )
                records = df_to_records(
                    df, search_term=term, search_location=config.DEFAULT_LOCATION,
                    requested_by_chat_id=chat_id)
                if not records:
                    ringkasan.append(f"⚪ {term}: 0")
                    continue
                unik, _ = db.deduplicate(records)
                simpan = await asyncio.to_thread(db.upsert_jobs, unik)
                total_simpan += simpan
                ringkasan.append(f"✅ {term}: {simpan}")
            except Exception as e:  # noqa: BLE001
                logger.exception("/carikerja gagal untuk '%s'", term)
                ringkasan.append(f"❌ {term}: {str(e)[:50]}")
    finally:
        st["berjalan"] = False

    teks = (f"✅ *{escape_md(judul)}* selesai: *{total_simpan} loker* "
            f"tersimpan/terupdate\n\n" + "\n".join(escape_md(r) for r in ringkasan))
    try:
        await status.edit_text(teks[:4000], parse_mode=ParseMode.MARKDOWN)
    except Exception:  # noqa: BLE001
        await context.bot.send_message(chat_id, teks[:4000])


def register(app: Application, is_allowed, escape_md) -> None:
    app.bot_data["is_allowed"] = is_allowed
    app.bot_data["escape_md"] = escape_md
    app.add_handler(CommandHandler("carikerja", carikerja_cmd))
    app.add_handler(CallbackQueryHandler(carikerja_callback, pattern=r"^kk:"))
    logger.info("Perintah /carikerja terdaftar (%s kelompok)", len(KELOMPOK))
