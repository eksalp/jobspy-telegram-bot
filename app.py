from __future__ import annotations

import logging
import os
import shlex
import threading

from flask import Flask, jsonify, request

import config
import db
from scraper import df_to_records, run_search
from telegram_api import edit_message, send_message
from web3career import find_matching_tag, search_web3career, web3career_to_records, VALID_TAGS
from lokerbumn import search_lokerbumn, lokerbumn_to_records
from astracareer import search_astra_career, astra_career_to_records
from talentics import search_talentics, talentics_to_records
from bca import search_bca, bca_to_records
from shopee import search_shopee, shopee_to_records
from pertamina_ptc import search_pertamina_ptc, pertamina_ptc_to_records
from shopee import search_shopee, shopee_to_records
from pertamina_ptc import search_pertamina_ptc, pertamina_ptc_to_records

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

HELP_TEXT = (
    "*JobSpy Bot*\n\n"
    "Cari loker dan simpan otomatis ke Supabase.\n\n"
    "*Format:*\n"
    "`/update <kata kunci> [opsi...]`\n\n"
    "*Opsi (boleh salah satu, boleh semua):*\n"
    "`--location <lokasi>`  contoh: --location \"Jakarta Selatan\"\n"
    "`--sites <situs>`  pisahkan koma, contoh: --sites indeed,linkedin\n"
    "  (pilihan: indeed, linkedin, glassdoor, google, zip-recruiter, bayt, naukri, "
    "web3career, lokerbumn, astracareer, talentics)\n"
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
    "`/update backend engineer --location Bandung --sites indeed,linkedin --results 50`\n\n"
    "\u23f3 Bot ini tidur kalau nganggur >15 menit (hosting gratis). Kalau balasan pertama "
    "lambat (~30-60 detik), itu wajar, dia lagi \"bangun\"."
)


def escape_md(text) -> str:
    """Escape karakter spesial Markdown (legacy) biar teks dinamis (search term,
    pesan error, dll) nggak bikin Telegram gagal parse.
    """
    if text is None:
        return ""
    text = str(text)
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def is_allowed(chat_id: int | str) -> bool:
    if not config.ALLOWED_CHAT_IDS:
        return True
    return str(chat_id) in config.ALLOWED_CHAT_IDS


def parse_update_args(raw_args: list[str]) -> dict:
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


def handle_update_command(chat_id, text: str) -> None:
    """Jalan di background thread supaya webhook bisa langsung balas 200 ke Telegram."""
    parts = text.split(maxsplit=1)
    args_text = parts[1] if len(parts) > 1 else ""

    try:
        raw_args = shlex.split(args_text)
    except ValueError as e:
        send_message(chat_id, f"Format perintah tidak valid: {e}")
        return

    options = parse_update_args(raw_args)
    search_terms = options["search_terms"]

    if not search_terms:
        send_message(
            chat_id,
            "Sertakan kata kunci pencarian, contoh:\n`/update data analyst`\n"
            "atau beberapa sekaligus:\n"
            "`/update data analyst; backend engineer; ui designer`",
        )
        return

    location = options["location"] or config.DEFAULT_LOCATION
    sites = options["sites"] or config.DEFAULT_SITES
    country = options["country"] or config.DEFAULT_COUNTRY_INDEED

    total_terms = len(search_terms)
    list_preview = ", ".join(search_terms)
    status = send_message(
        chat_id,
        f"🔍 Memproses {total_terms} pencarian: *{escape_md(list_preview)}*\n"
        f"di *{location}* ({', '.join(sites)})...\n"
        f"Ini bisa makan waktu beberapa saat, mohon tunggu.",
    )
    status_message_id = status.get("result", {}).get("message_id")

    def update_status(msg: str) -> None:
        if status_message_id:
            edit_message(chat_id, status_message_id, msg)
        else:
            send_message(chat_id, msg)

    results_summary: list[str] = []

    for idx, search_term in enumerate(search_terms, start=1):
        update_status(f"🔍 ({idx}/{total_terms}) Mencari *{escape_md(search_term)}*...")

        combined_records: list[dict] = []
        term_notes: list[str] = []

        extra_sites = {"web3career", "lokerbumn", "astracareer", "talentics", "bca", "shopee", "pertamina_ptc"}
        jobspy_sites = [s for s in sites if s not in extra_sites]
        use_web3career = "web3career" in sites
        use_lokerbumn = "lokerbumn" in sites
        use_astracareer = "astracareer" in sites
        use_talentics = "talentics" in sites
        use_bca = "bca" in sites
        use_shopee = "shopee" in sites
        use_pertamina_ptc = "pertamina_ptc" in sites
        use_shopee = "shopee" in sites
        use_pertamina_ptc = "pertamina_ptc" in sites

        if jobspy_sites:
            try:
                df = run_search(
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
                    jobs = search_web3career(
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
                        search_location=options["location"],
                        requested_by_chat_id=chat_id,
                        search_remote=options["remote"],
                    )
                    combined_records.extend(w3_records)
                    term_notes.append(f"{len(w3_records)} dari web3career (tag: {tag})")

        if use_lokerbumn:
            try:
                posts = search_lokerbumn(
                    query=search_term,
                    limit=options["results"] or config.DEFAULT_RESULTS_WANTED,
                )
            except Exception as e:
                logger.exception("Gagal ambil data lokerbumn untuk '%s'", search_term)
                term_notes.append(f"❌ lokerbumn gagal ({escape_md(e)})")
            else:
                lb_records = lokerbumn_to_records(
                    posts,
                    search_term=search_term,
                    search_location=location,
                    requested_by_chat_id=chat_id,
                )
                combined_records.extend(lb_records)
                term_notes.append(f"{len(lb_records)} dari lokerbumn")

        if use_astracareer:
            try:
                jobs = search_astra_career(
                    query=search_term,
                    limit=options["results"] or config.DEFAULT_RESULTS_WANTED,
                )
            except Exception as e:
                logger.exception("Gagal ambil data astracareer untuk '%s'", search_term)
                term_notes.append(f"❌ astracareer gagal ({escape_md(e)})")
            else:
                ac_records = astra_career_to_records(
                    jobs,
                    search_term=search_term,
                    search_location=location,
                    requested_by_chat_id=chat_id,
                )
                combined_records.extend(ac_records)
                term_notes.append(f"{len(ac_records)} dari astracareer")

        if use_pertamina_ptc:
            try:
                jobs = search_pertamina_ptc(
                    query=search_term,
                    limit=options["results"] or config.DEFAULT_RESULTS_WANTED,
                )
            except Exception as e:
                logger.exception("Gagal ambil data Pertamina PTC untuk '%s'", search_term)
                term_notes.append(f"❌ Pertamina PTC gagal ({escape_md(e)})")
            else:
                ptc_recs = pertamina_ptc_to_records(
                    jobs,
                    search_term=search_term,
                    search_location=location,
                    requested_by_chat_id=chat_id,
                )
                combined_records.extend(ptc_recs)
                term_notes.append(f"{len(ptc_recs)} dari Pertamina PTC")

        if use_talentics:
            try:
                jobs = search_talentics(
                    query=search_term,
                    limit=options["results"] or config.DEFAULT_RESULTS_WANTED,
                )
            except Exception as e:
                logger.exception("Gagal ambil data talentics untuk '%s'", search_term)
                term_notes.append(f"❌ talentics gagal ({escape_md(e)})")
            else:
                tl_records = talentics_to_records(
                    jobs,
                    search_term=search_term,
                    search_location=location,
                    requested_by_chat_id=chat_id,
                )
                combined_records.extend(tl_records)
                term_notes.append(f"{len(tl_records)} dari talentics")

        if use_bca:
            try:
                jobs = search_bca(
                    query=search_term,
                    limit=options["results"] or config.DEFAULT_RESULTS_WANTED,
                )
            except Exception as e:
                logger.exception("Gagal ambil data BCA untuk '%s'", search_term)
                term_notes.append(f"❌ BCA gagal ({escape_md(e)})")
            else:
                bca_recs = bca_to_records(
                    jobs,
                    search_term=search_term,
                    search_location=location,
                    requested_by_chat_id=chat_id,
                )
                combined_records.extend(bca_recs)
                term_notes.append(f"{len(bca_recs)} dari BCA")

        if use_shopee:
            try:
                jobs = search_shopee(
                    query=search_term,
                    limit=options["results"] or config.DEFAULT_RESULTS_WANTED,
                )
            except Exception as e:
                logger.exception("Gagal ambil data Shopee untuk '%s'", search_term)
                term_notes.append(f"❌ Shopee gagal ({escape_md(e)})")
            else:
                shopee_recs = shopee_to_records(
                    jobs,
                    search_term=search_term,
                    search_location=location,
                    requested_by_chat_id=chat_id,
                )
                combined_records.extend(shopee_recs)
                term_notes.append(f"{len(shopee_recs)} dari Shopee")

        if not combined_records:
            results_summary.append(f"⚪ *{escape_md(search_term)}*: {escape_md(' | '.join(term_notes))}")
            continue

        try:
            saved = db.upsert_jobs(combined_records)
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
    update_status(final_text)


@app.route("/", methods=["GET"])
def health():
    return jsonify(status="ok"), 200


@app.route(f"/webhook/{config.TELEGRAM_WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if config.TELEGRAM_WEBHOOK_SECRET and secret_header != config.TELEGRAM_WEBHOOK_SECRET:
        logger.warning("Webhook request dengan secret token salah, ditolak.")
        return jsonify(ok=False), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message") or {}
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "") or ""

    if not chat_id or not text:
        return jsonify(ok=True), 200

    if not is_allowed(chat_id):
        send_message(chat_id, "Maaf, kamu tidak punya akses ke bot ini.")
        return jsonify(ok=True), 200

    if text.startswith("/start") or text.startswith("/help"):
        send_message(chat_id, HELP_TEXT)
    elif text.startswith("/update"):
        threading.Thread(target=handle_update_command, args=(chat_id, text), daemon=True).start()
    else:
        send_message(chat_id, "Perintah tidak dikenali. Kirim /help untuk lihat cara pakai.")

    return jsonify(ok=True), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
