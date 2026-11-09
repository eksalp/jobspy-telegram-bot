from __future__ import annotations

import asyncio
import logging
import shlex

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import config
import db
from scraper import df_to_records, run_search
from web3career import find_matching_tag, search_web3career, web3career_to_records, VALID_TAGS

import sites

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

HELP_TEXT = (
    "*JobSpy Bot*\n\n"
    "Cari loker dan simpan otomatis ke Supabase.\n\n"
    "*Format:*\n"
    "`/update <kata kunci> [opsi...]`\n\n"
    "*Opsi (boleh salah satu, boleh semua):*\n"
    "`--location <lokasi>`  contoh: --location \"Jakarta Selatan\"\n"
    "`--sites <situs>`  pisahkan koma, contoh: --sites indeed,linkedin\n"
    "  (situs JobSpy: indeed, linkedin, glassdoor, google, zip-recruiter, bayt, "
    "naukri — plus situs karir perusahaan, lihat `/sites`)\n"
    "  Alias grup: `all` (semua situs perusahaan), `verified` (yang sudah "
    "terkonfirmasi jalan), `fast` (tanpa yang butuh browser), `tag:bank`, "
    "`tag:bumn`, `tag:fmcg`, `tag:tech`.\n"
    "  *web3career* khusus loker web3/blockchain/crypto, butuh kata kunci berupa tag "
    "(mis. solidity, defi, smart-contract, blockchain, rust) — kata kunci bebas akan "
    "dicocokkan otomatis ke tag terdekat.\n"
    "  *lokerbumn* khusus loker BUMN Indonesia (lokerbumn.com).\n"
    "  *astracareer* & *talentics* eksperimental (situs JS), bisa lebih lambat/kurang "
    "stabil dari situs lain.\n"
    "  Buat *lokerbumn/astracareer/talentics*: pakai kata kunci `semua` (atau `all`) "
    "buat ambil semua loker di situs itu tanpa filter kata kunci apapun.\n"
    "`--country <negara>`  contoh: --country indonesia (dipakai Indeed & Glassdoor)\n"
    "`--results <angka>`  jumlah maksimal loker per situs, default "
    f"{config.DEFAULT_RESULTS_WANTED}\n"
    "`--hours <angka>`  hanya loker yang diposting N jam terakhir, default "
    f"{config.DEFAULT_HOURS_OLD}\n"
    "`--remote`  hanya loker remote\n\n"
    "*Contoh:*\n"
    "`/update data analyst`\n"
    "`/update backend engineer --location Bandung --sites indeed,linkedin --results 50`\n"
    "`/update UI UX designer --remote --hours 24`\n\n"
    "*Banyak kata kunci sekaligus* (pisahkan dengan `;`, opsi berlaku ke semuanya):\n"
    "`/update data analyst; backend engineer; ui designer --location Bandung`\n\n"
    "Default kalau opsi tidak diisi: lokasi *"
    f"{config.DEFAULT_LOCATION}*, situs *{', '.join(config.DEFAULT_SITES)}*."
)


def escape_md(text) -> str:
    """Escape karakter spesial Markdown (legacy) biar teks dinamis (search term,
    pesan error, dll) nggak bikin Telegram gagal parse & bot crash.
    """
    if text is None:
        return ""
    text = str(text)
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def is_allowed(chat_id: int) -> bool:
    if not config.ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in config.ALLOWED_CHAT_IDS


def parse_update_args(raw_args: list[str]) -> dict:
    """Parse token setelah /update jadi search_terms (list) + opsi.
    Token yang bukan flag digabung lalu dipecah berdasarkan ';' jadi beberapa
    search term, biar bisa /update data analyst; backend engineer; ui designer
    """
    options = {
        "location": None,
        "sites": None,
        "country": None,
        "results": None,
        "hours": None,
        "remote": False,
    }
    rest_tokens: list[str] = []

    i = 0
    while i < len(raw_args):
        token = raw_args[i]
        if token == "--location" and i + 1 < len(raw_args):
            options["location"] = raw_args[i + 1]
            i += 2
        elif token == "--sites" and i + 1 < len(raw_args):
            options["sites"] = [s.strip() for s in raw_args[i + 1].split(",") if s.strip()]
            i += 2
        elif token == "--country" and i + 1 < len(raw_args):
            options["country"] = raw_args[i + 1]
            i += 2
        elif token == "--results" and i + 1 < len(raw_args):
            options["results"] = int(raw_args[i + 1])
            i += 2
        elif token == "--hours" and i + 1 < len(raw_args):
            options["hours"] = int(raw_args[i + 1])
            i += 2
        elif token == "--remote":
            options["remote"] = True
            i += 1
        else:
            rest_tokens.append(token)
            i += 1

    joined = " ".join(rest_tokens)
    options["search_terms"] = [t.strip() for t in joined.split(";") if t.strip()]
    return options


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)


async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info("Perintah /update dari chat_id=%s: %s", chat_id, update.message.text)

    if not is_allowed(chat_id):
        await update.message.reply_text("Maaf, kamu tidak punya akses ke bot ini.")
        return

    raw_text = update.message.text or ""
    # buang "/update" (dan "@botname" kalau ada) dari depan teks
    parts = raw_text.split(maxsplit=1)
    args_text = parts[1] if len(parts) > 1 else ""

    try:
        raw_args = shlex.split(args_text)
    except ValueError as e:
        await update.message.reply_text(f"Format perintah tidak valid: {e}")
        return

    options = parse_update_args(raw_args)
    search_terms = options["search_terms"]

    if not search_terms:
        await update.message.reply_text(
            "Sertakan kata kunci pencarian, contoh:\n`/update data analyst`\n"
            "atau beberapa sekaligus:\n"
            "`/update data analyst; backend engineer; ui designer`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    location = options["location"] or config.DEFAULT_LOCATION
    sites_requested = options["sites"] or config.DEFAULT_SITES
    country = options["country"] or config.DEFAULT_COUNTRY_INDEED

    total_terms = len(search_terms)
    list_preview = ", ".join(search_terms)
    status_msg = await update.message.reply_text(
        f"🔍 Memproses {total_terms} pencarian: *{escape_md(list_preview)}*\n"
        f"di *{location}* ({escape_md(', '.join(sites_requested))})...\n"
        f"Ini bisa makan waktu beberapa saat, mohon tunggu.",
        parse_mode=ParseMode.MARKDOWN,
    )

    results_summary: list[str] = []

    for idx, search_term in enumerate(search_terms, start=1):
        try:
            await status_msg.edit_text(
                f"🔍 ({idx}/{total_terms}) Mencari *{escape_md(search_term)}*...",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass  # kalau gagal edit (misal isi sama), abaikan, lanjut proses

        combined_records: list[dict] = []
        term_notes: list[str] = []

        # Registry menentukan situs mana yang punya adapter sendiri; sisanya
        # diserahkan ke JobSpy. Menambah perusahaan baru cukup di
        # sites/companies.py, file ini tidak perlu disentuh lagi.
        site_specs, jobspy_sites = sites.resolve(sites_requested)
        use_web3career = "web3career" in jobspy_sites
        jobspy_sites = [s for s in jobspy_sites if s != "web3career"]

        if jobspy_sites:
            try:
                df = await asyncio.to_thread(
                    run_search,
                    search_term=search_term,
                    location=location,
                    sites=jobspy_sites,
                    country_indeed=country,
                    results_wanted=options["results"],
                    hours_old=options["hours"],
                    is_remote=options["remote"],
                )
            except Exception as e:
                logger.exception("Gagal scraping untuk '%s'", search_term)
                term_notes.append(f"❌ situs biasa gagal ({escape_md(e)})")
            else:
                if df is not None and not df.empty:
                    combined_records.extend(
                        df_to_records(
                            df,
                            search_term=search_term,
                            search_location=location,
                            requested_by_chat_id=chat_id,
                            is_remote_filter=options["remote"],
                        )
                    )
                    term_notes.append(f"{len(df)} dari situs biasa")
                else:
                    term_notes.append("0 dari situs biasa")

        if use_web3career:
            tag = find_matching_tag(search_term)
            if not tag:
                term_notes.append(
                    f"⚠️ web3career: \"{escape_md(search_term)}\" tidak cocok dengan tag manapun "
                    f"(contoh tag valid: {', '.join(VALID_TAGS[:8])}, ...)"
                )
            else:
                try:
                    jobs = await asyncio.to_thread(
                        search_web3career,
                        tag=tag,
                        remote=options["remote"],
                        country=options["country"],
                        limit=options["results"] or config.DEFAULT_RESULTS_WANTED,
                    )
                except Exception as e:
                    logger.exception("Gagal ambil data web3career untuk '%s'", search_term)
                    term_notes.append(f"❌ web3career gagal ({escape_md(e)})")
                else:
                    w3_records = web3career_to_records(
                        jobs,
                        search_term=search_term,
                        search_location=options["location"],  # None kalau user gak isi --location, biar diisi per-job
                        requested_by_chat_id=chat_id,
                        search_remote=options["remote"],
                    )
                    combined_records.extend(w3_records)
                    term_notes.append(f"{len(w3_records)} dari web3career (tag: {tag})")

        for spec in site_specs:
            try:
                recs = await asyncio.to_thread(
                    sites.run,
                    spec,
                    query=search_term,
                    limit=options["results"] or config.DEFAULT_RESULTS_WANTED,
                    chat_id=chat_id,
                    search_location=location,
                )
            except Exception as e:
                logger.exception("Gagal ambil data %s untuk '%s'", spec.name, search_term)
                term_notes.append(f"❌ {escape_md(spec.label)} gagal ({escape_md(e)})")
                continue
            combined_records.extend(recs)
            term_notes.append(f"{len(recs)} dari {escape_md(spec.label)}")

        if not combined_records:
            results_summary.append(f"⚪ *{escape_md(search_term)}*: {escape_md(' | '.join(term_notes))}")
            continue

        try:
            saved = await asyncio.to_thread(db.upsert_jobs, combined_records)
        except Exception as e:
            logger.exception("Gagal upsert ke Supabase untuk '%s'", search_term)
            results_summary.append(
                f"⚠️ *{escape_md(search_term)}*: {len(combined_records)} ditemukan, gagal simpan ({escape_md(e)})"
            )
            continue

        results_summary.append(
            f"✅ *{escape_md(search_term)}*: {saved} loker tersimpan/terupdate ({escape_md(' | '.join(term_notes))})"
        )

    final_text = (
        f"Selesai memproses {total_terms} pencarian di *{location}*:\n\n"
        + "\n".join(results_summary)
    )
    await status_msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN)


async def scrapeall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Scrape semua situs sekaligus tanpa perlu ketik /update satu per satu."""
    chat_id = update.effective_chat.id
    logger.info("Perintah /scrapeall dari chat_id=%s", chat_id)

    if not is_allowed(chat_id):
        await update.message.reply_text("Maaf, kamu tidak punya akses ke bot ini.")
        return

    sites_requested = config.SCRAPE_ALL_SITES
    results_per_site = config.SCRAPE_ALL_RESULTS
    location = config.DEFAULT_LOCATION
    sites_preview = escape_md(", ".join(sites_requested))

    status_msg = await update.message.reply_text(
        f"\U0001f504 Memulai scraping dari *{len(sites_requested)} sumber*:\n"
        f"{sites_preview}\n\n"
        "Ini bisa makan waktu beberapa menit, mohon tunggu...",
        parse_mode=ParseMode.MARKDOWN,
    )

    combined_records: list[dict] = []
    site_notes: list[str] = []

    site_specs, jobspy_sites = sites.resolve(sites_requested)
    use_web3career = "web3career" in jobspy_sites
    jobspy_sites = [s for s in jobspy_sites if s != "web3career"]

    # JobSpy sites (indeed, linkedin, dll)
    if jobspy_sites:
        try:
            await status_msg.edit_text(
                f"\U0001f50d Mencari dari: *{escape_md(', '.join(jobspy_sites))}*...",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        try:
            df = await asyncio.to_thread(
                run_search,
                search_term="",
                location=location,
                sites=jobspy_sites,
                country_indeed=config.DEFAULT_COUNTRY_INDEED,
                results_wanted=results_per_site,
                hours_old=config.DEFAULT_HOURS_OLD,
                is_remote=False,
            )
            if df is not None and not df.empty:
                combined_records.extend(df_to_records(
                    df, search_term="scrapeall",
                    search_location=location, requested_by_chat_id=chat_id
                ))
                site_notes.append(f"\u2705 {', '.join(jobspy_sites)}: {len(df)} loker")
            else:
                site_notes.append(f"\u26aa {', '.join(jobspy_sites)}: 0 loker")
        except Exception as e:
            logger.exception("Gagal scrape jobspy sites")
            site_notes.append(f"\u274c {', '.join(jobspy_sites)}: gagal ({escape_md(e)})")

    for idx, spec in enumerate(site_specs, start=1):
        try:
            await status_msg.edit_text(
                f"\U0001f50d ({idx}/{len(site_specs)}) "
                f"Mencari dari *{escape_md(spec.label)}*...",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        try:
            recs = await asyncio.to_thread(
                sites.run, spec, query="semua",
                limit=results_per_site, chat_id=chat_id, search_location=location,
            )
            combined_records.extend(recs)
            site_notes.append(f"\u2705 {spec.label}: {len(recs)} loker")
        except Exception as e:
            logger.exception("Gagal scrape %s", spec.name)
            site_notes.append(f"\u274c {spec.label}: gagal ({escape_md(e)})")

    if use_web3career:
        try:
            await status_msg.edit_text(
                f"\U0001f50d ({len(site_notes)+1}/{len(sites_requested)}) "
                "Mencari dari *web3career*...",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
        try:
            jobs_w3 = await asyncio.to_thread(
                search_web3career, tag="blockchain", limit=results_per_site
            )
            recs_w3 = web3career_to_records(
                jobs_w3, search_term="scrapeall",
                search_location=None, requested_by_chat_id=chat_id, search_remote=False
            )
            combined_records.extend(recs_w3)
            site_notes.append(f"\u2705 web3career: {len(recs_w3)} loker")
        except Exception as e:
            logger.exception("Gagal scrape web3career")
            site_notes.append(f"\u274c web3career: gagal ({escape_md(e)})")

    saved = 0
    if combined_records:
        try:
            unique_records, dupes = db.deduplicate(combined_records)
            if dupes:
                site_notes.append(
                    "\u2139\ufe0f " + escape_md(
                        f"{sum(dupes.values())} duplikat dibuang "
                        f"({', '.join(f'{k}: {v}' for k, v in sorted(dupes.items()))})"
                    )
                )
            saved = await asyncio.to_thread(db.upsert_jobs, unique_records)
        except Exception as e:
            logger.exception("Gagal upsert ke Supabase")
            await status_msg.edit_text(
                f"\u26a0\ufe0f Ditemukan {len(combined_records)} loker total, "
                f"tapi gagal menyimpan: {escape_md(e)}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

    summary = "\n".join(site_notes)
    await status_msg.edit_text(
        f"\u2705 *Scrape selesai!* {saved} loker tersimpan/terupdate\n\n{summary}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def sites_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tampilkan semua situs karir yang terdaftar beserta statusnya."""
    chat_id = str(update.effective_chat.id)
    if not is_allowed(chat_id):
        await update.message.reply_text("Maaf, kamu tidak punya akses ke bot ini.")
        return

    total = len(sites.REGISTRY)
    verified = sum(1 for s in sites.REGISTRY.values() if s.verified)
    await update.message.reply_text(
        f"*Situs karir terdaftar* ({verified}/{total} terkonfirmasi)\n"
        "✅ sudah dites  ⚠️ belum dites  🐢 butuh browser (lambat)\n\n"
        + sites.catalog()
        + "\n\nPakai lewat `--sites <nama>`, atau alias `all` / `verified` / `fast`.",
        parse_mode=ParseMode.MARKDOWN,
    )


def main() -> None:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("update", update_cmd))
    app.add_handler(CommandHandler("scrapeall", scrapeall_cmd))
    app.add_handler(CommandHandler("sites", sites_cmd))

    # Perintah per situs (/magenta, /dealls, /pertamina_pdc, ...) dan
    # /updateall, dibangkitkan otomatis dari registry. Sekalian memasang
    # menu hamburger Telegram lewat set_my_commands().
    import site_commands
    site_commands.register_site_commands(app, is_allowed, escape_md)

    import hapusdata
    hapusdata.register(app, is_allowed, escape_md)

    import kata_kunci
    kata_kunci.register(app, is_allowed, escape_md)

    import reset_db
    reset_db.register(app, is_allowed, escape_md)

    logger.info("Bot mulai polling...")

    # python-telegram-bot 21.4 memanggil asyncio.get_event_loop() di dalam
    # run_polling(). Sampai Python 3.12 pemanggilan itu otomatis membuat loop
    # baru kalau belum ada; sejak 3.14 perilaku itu dihapus dan malah melempar
    # RuntimeError. Jadi loop-nya kita siapkan sendiri dulu.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
