import os

from dotenv import load_dotenv

load_dotenv()


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

ALLOWED_CHAT_IDS = set(_split_csv(os.environ.get("ALLOWED_CHAT_IDS")))

DEFAULT_SITES = _split_csv(os.environ.get("DEFAULT_SITES", "indeed,linkedin"))
DEFAULT_LOCATION = os.environ.get("DEFAULT_LOCATION", "Indonesia")
DEFAULT_COUNTRY_INDEED = os.environ.get("DEFAULT_COUNTRY_INDEED", "Indonesia")
DEFAULT_RESULTS_WANTED = int(os.environ.get("DEFAULT_RESULTS_WANTED", "30"))
DEFAULT_HOURS_OLD = int(os.environ.get("DEFAULT_HOURS_OLD", "72"))

# Daftar situs yang discrap sekaligus saat /scrapeall dijalankan.
# Pisahkan dengan koma. Situs custom (bca, shopee, astracareer, dll) bisa
# dicampur dengan situs JobSpy (indeed, linkedin, dll).
# "verified" = semua situs perusahaan yang endpoint-nya sudah dikonfirmasi.
# Alias lain: "all" (semua), "fast" (tanpa Playwright), "tag:bank", "tag:bumn".
SCRAPE_ALL_SITES = _split_csv(os.environ.get(
    "SCRAPE_ALL_SITES",
    "indeed,linkedin,verified"
))
# Jumlah maksimal loker per situs saat /scrapeall
SCRAPE_ALL_RESULTS = int(os.environ.get("SCRAPE_ALL_RESULTS", "50"))

# Hanya dipakai oleh app.py (mode webhook, untuk deploy di Render dkk)
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Token API web3.career, gratis, daftar di https://web3.career/web3-jobs-api
WEB3CAREER_API_TOKEN = os.environ.get("WEB3CAREER_API_TOKEN", "")
