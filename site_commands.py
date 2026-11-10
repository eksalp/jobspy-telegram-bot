from __future__ import annotations

"""
Perintah Telegram per situs, dibangkitkan otomatis dari registry.

Menambahkan satu perintah untuk tiap situs terdaftar:

    /pertamina_pdc   scrape Pertamina PDC saja
    /magenta         scrape MAGENTA saja
    /dealls          scrape Dealls saja
    ...

Plus:

    /updateall       scrape SEMUA situs sekaligus (sama seperti /scrapeall)
    /sites           daftar situs beserta statusnya

Perintah-perintah ini juga didaftarkan ke Telegram lewat set_my_commands(),
sehingga muncul di menu hamburger dan autocomplete saat mengetik "/".

Tidak perlu mengubah apa pun saat menambah situs baru: daftar perintahnya
dibangkitkan dari sites.REGISTRY, jadi situs baru otomatis dapat perintahnya
sendiri.
"""

import asyncio
import logging
from typing import Callable

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import db
import sites
from bersih_lama import bersihkan, sekarang, tandai

logger = logging.getLogger(__name__)

# Telegram membatasi 100 perintah, dan nama perintah hanya boleh huruf kecil,
# angka, dan garis bawah (maks 32 karakter).
MAX_COMMANDS = 100


def _nama_perintah(site_name: str) -> str:
    """Ubah nama situs jadi nama perintah yang sah menurut Telegram."""
    bersih = "".join(c for c in site_name.lower() if c.isalnum() or c == "_")
    return bersih[:32]


async def _jalankan_situs(
    update: Update,
    spec: sites.SiteSpec,
    escape_md: Callable[[object], str],
) -> None:
    """Scrape satu situs lalu laporkan hasilnya."""
    chat_id = str(update.effective_chat.id)
    hasil = await update.message.reply_text(
        f"\U0001f50d Mengambil lowongan dari *{escape_md(spec.label)}*...",
        parse_mode=ParseMode.MARKDOWN,
    )

    batas = sekarang()
    try:
        records = await asyncio.to_thread(
            sites.run,
            spec,
            query="semua",
            limit=config.SCRAPE_ALL_RESULTS,
            chat_id=chat_id,
            search_location=config.DEFAULT_LOCATION,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Gagal scrape %s", spec.name)
        await hasil.edit_text(
            f"\u274c *{escape_md(spec.label)}* gagal:\n{escape_md(e)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not records:
        await hasil.edit_text(
            f"\u26aa *{escape_md(spec.label)}*: tidak ada lowongan ditemukan.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    unik, kembar = db.deduplicate(records)
    unik = tandai(unik)
    try:
        tersimpan = await asyncio.to_thread(db.upsert_jobs, unik)
    except Exception as e:  # noqa: BLE001
        logger.exception("Gagal menyimpan hasil %s", spec.name)
        await hasil.edit_text(
            f"\u26a0\ufe0f Dapat {len(unik)} loker dari "
            f"*{escape_md(spec.label)}*, tapi gagal disimpan:\n{escape_md(e)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    catatan = ""
    if kembar:
        catatan = f"\n\u2139\ufe0f {sum(kembar.values())} duplikat dibuang"
    tutup = await asyncio.to_thread(
        bersihkan, sorted({str(r["site"]) for r in unik if r.get("site")}),
        batas, tersimpan)
    if tutup:
        catatan += "\n" + escape_md(tutup.strip(" ()"))

    await hasil.edit_text(
        f"\u2705 *{escape_md(spec.label)}*: {tersimpan} loker "
        f"tersimpan/terupdate{catatan}",
        parse_mode=ParseMode.MARKDOWN,
    )


def _buat_handler(spec_name: str, is_allowed, escape_md):
    """Bikin callback untuk satu situs.

    Spec dicari saat perintah dijalankan, bukan saat pendaftaran, supaya
    perubahan di registry langsung terpakai tanpa restart handler.
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.effective_chat.id)
        if not is_allowed(chat_id):
            await update.message.reply_text(
                "Maaf, kamu tidak punya akses ke bot ini.")
            return

        spec = sites.get(spec_name)
        if spec is None:
            await update.message.reply_text(
                f"Situs '{spec_name}' sudah tidak terdaftar.")
            return

        logger.info("Perintah /%s dari chat_id=%s",
                    _nama_perintah(spec_name), chat_id)
        await _jalankan_situs(update, spec, escape_md)

    return handler


def _buat_handler_semua(is_allowed, escape_md):
    """Callback /updateall — semua situs, satu per satu.

    PENTING: upsert ke Supabase dilakukan PER SITUS, di dalam loop ini --
    BUKAN dikumpulkan dulu lalu disimpan sekali di akhir. Versi lama
    menumpuk semua hasil scrape di memory (`semua.extend(records)`) dan
    baru memanggil db.upsert_jobs() satu kali setelah SEMUA situs selesai.

    Akibatnya: (1) selama proses berjalan, Supabase/Jobly terlihat kosong
    total walau sudah banyak situs yang sukses di-scrape -- membingungkan
    saat memantau progres; dan (2) kalau proses mati di tengah jalan (mis.
    situs terakhir yang lambat seperti TopLoker, atau bot di-restart),
    SEMUA hasil dari situs-situs sebelumnya ikut hilang karena belum
    pernah benar-benar terkirim ke database.

    Dedup tetap aman dilakukan per situs (bukan global di akhir): kunci
    dedup-nya (site, job_id) sudah menyertakan nama situs, jadi dedup per
    situs dan dedup gabungan menghasilkan hasil yang sama persis.
    """

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = str(update.effective_chat.id)
        if not is_allowed(chat_id):
            await update.message.reply_text(
                "Maaf, kamu tidak punya akses ke bot ini.")
            return

        specs, _ = sites.resolve(["all"])
        status = await update.message.reply_text(
            f"\U0001f504 Mengambil dari *{len(specs)} situs*...",
            parse_mode=ParseMode.MARKDOWN,
        )

        catatan: list[str] = []
        total_tersimpan = 0
        total_kembar = 0

        for i, spec in enumerate(specs, start=1):
            try:
                await status.edit_text(
                    f"\U0001f50d ({i}/{len(specs)}) "
                    f"*{escape_md(spec.label)}*...",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:  # noqa: BLE001
                pass

            batas = sekarang()
            try:
                records = await asyncio.to_thread(
                    sites.run, spec, query="semua",
                    limit=config.SCRAPE_ALL_RESULTS, chat_id=chat_id,
                    search_location=config.DEFAULT_LOCATION,
                )
            except Exception as e:  # noqa: BLE001
                logger.exception("Gagal scrape %s", spec.name)
                catatan.append(f"\u274c {spec.label}: {str(e)[:60]}")
                continue

            if not records:
                catatan.append(f"\u26aa {spec.label}: 0")
                continue

            # Disimpan SEKARANG, sebelum lanjut ke situs berikutnya --
            # bukan ditumpuk dulu. Lihat catatan fungsi di atas.
            unik, kembar = db.deduplicate(records)
            unik = tandai(unik)
            try:
                tersimpan = await asyncio.to_thread(db.upsert_jobs, unik)
            except Exception as e:  # noqa: BLE001
                logger.exception("Gagal menyimpan hasil %s", spec.name)
                catatan.append(
                    f"\u26a0\ufe0f {spec.label}: {len(unik)} didapat, "
                    f"GAGAL disimpan ({str(e)[:50]})"
                )
                continue

            total_tersimpan += tersimpan
            total_kembar += sum(kembar.values())
            tutup = await asyncio.to_thread(
                bersihkan, sorted({str(r["site"]) for r in unik if r.get("site")}),
                batas, tersimpan)
            catatan.append(f"\u2705 {spec.label}: {tersimpan}{tutup}")

        ringkas = "\n".join(escape_md(c) for c in catatan)
        if total_kembar:
            ringkas += f"\n\n\u2139\ufe0f {total_kembar} duplikat dibuang"

        if total_tersimpan == 0:
            await status.edit_text(
                f"\u26a0\ufe0f Tidak ada lowongan yang berhasil disimpan.\n\n"
                f"{ringkas}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await status.edit_text(
            f"\u2705 *{total_tersimpan} loker* tersimpan/terupdate\n\n{ringkas}",
            parse_mode=ParseMode.MARKDOWN,
        )

    return handler


async def _pasang_menu(app: Application) -> None:
    """Daftarkan perintah ke Telegram agar muncul di menu hamburger.

    `/scrapeall` sengaja TIDAK dimasukkan ke sini — sudah digantikan
    `/updateall` dan menampilkan keduanya cuma membingungkan (dua perintah,
    fungsi sama). Handler `/scrapeall` di bot.py tetap aktif untuk siapa pun
    yang masih terbiasa mengetiknya manual; ia cuma hilang dari daftar
    autocomplete, tidak dihapus.
    """
    perintah = [
        BotCommand("start", "Mulai & lihat cara pakai"),
        BotCommand("help", "Bantuan lengkap"),
        BotCommand("update", "Cari lowongan dengan kata kunci"),
        BotCommand("updateall", "Scrape semua situs sekaligus"),
        BotCommand("carikerja", "Cari Indeed & LinkedIn pakai kata kunci siap pakai"),
        BotCommand("sites", "Daftar situs dan statusnya"),
    ]

    # Situs terverifikasi lebih dulu, lalu sisanya — supaya yang paling
    # berguna muncul di atas daftar menu.
    urut = sorted(
        sites.REGISTRY.values(),
        key=lambda s: (not s.verified, s.name),
    )
    for spec in urut:
        if len(perintah) >= MAX_COMMANDS:
            logger.warning("Batas %s perintah Telegram tercapai, "
                           "sisanya tidak dimasukkan ke menu", MAX_COMMANDS)
            break
        keterangan = f"Scrape {spec.label}"
        if spec.needs_browser:
            keterangan += " (lambat)"
        perintah.append(
            BotCommand(_nama_perintah(spec.name), keterangan[:256]))

    try:
        await app.bot.set_my_commands(perintah)
        logger.info("Menu Telegram diperbarui: %s perintah", len(perintah))
    except Exception as e:  # noqa: BLE001
        logger.warning("Gagal memasang menu perintah: %s", e)


def register_site_commands(app: Application, is_allowed, escape_md) -> None:
    """Daftarkan /namasitus untuk tiap situs, /updateall, dan menu Telegram.

    Dipanggil dari bot.py setelah handler lain terpasang:

        import site_commands
        site_commands.register_site_commands(app, is_allowed, escape_md)
    """
    for spec in sites.REGISTRY.values():
        nama = _nama_perintah(spec.name)
        if not nama:
            continue
        app.add_handler(CommandHandler(
            nama, _buat_handler(spec.name, is_allowed, escape_md)))

        # Alias tanpa garis bawah, mis. /pertaminapdc untuk pertamina_pdc
        tanpa_garis = nama.replace("_", "")
        if tanpa_garis != nama and tanpa_garis:
            app.add_handler(CommandHandler(
                tanpa_garis, _buat_handler(spec.name, is_allowed, escape_md)))

    app.add_handler(CommandHandler(
        "updateall", _buat_handler_semua(is_allowed, escape_md)))

    # post_init dipakai untuk memasang menu setelah bot terhubung. Kalau bot.py
    # sudah punya post_init sendiri, keduanya dijalankan berurutan.
    sebelumnya = app.post_init

    async def post_init(application: Application) -> None:
        if sebelumnya is not None:
            await sebelumnya(application)
        await _pasang_menu(application)

    app.post_init = post_init

    logger.info("Perintah per situs terdaftar: %s situs", len(sites.REGISTRY))