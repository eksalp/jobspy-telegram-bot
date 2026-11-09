"""Cek header yang dipakai halaman Talentics saat memanggil API, lalu coba
panggil API halaman 2 lewat sesi browser yang sama.

    python cek_talentics3.py

Hanya membaca. Nilai token/cookie DISAMARKAN di output, jadi aman ditempel.
Tempel SELURUH output-nya ke chat.
"""
import json

from playwright.sync_api import sync_playwright

BASE = "https://jobs.talentics.id"


def samarkan(nama, nilai):
    rahasia = ("authorization", "cookie", "token", "csrf", "xsrf", "session", "key")
    if any(r in nama.lower() for r in rahasia):
        return f"<{len(nilai)} karakter, disamarkan>"
    return nilai[:120]


def pendek(v, n=200):
    t = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return t if len(t) <= n else t[:n] + "...(dipotong)"


tertangkap = {}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    page = ctx.new_page()

    def catat(req):
        if "/ajaxs/jobs" in req.url and "headers" not in tertangkap:
            tertangkap["url"] = req.url
            tertangkap["method"] = req.method
            tertangkap["headers"] = req.all_headers()

    page.on("request", catat)
    page.goto(f"{BASE}/jobs", timeout=40000, wait_until="networkidle")
    page.wait_for_timeout(3000)

    print("=== request API yang dikirim halaman ===")
    print(tertangkap.get("method"), tertangkap.get("url"))
    for k, v in sorted((tertangkap.get("headers") or {}).items()):
        print(f"  {k:<28} {samarkan(k, v)}")

    print("\n=== cookie di browser (nama saja) ===")
    print([c["name"] for c in ctx.cookies()])

    # Coba halaman 2 dengan header yang sama, lewat sesi browser yang sama
    h = {k: v for k, v in (tertangkap.get("headers") or {}).items()
         if not k.startswith(":") and k.lower() not in ("content-length", "host")}
    r = ctx.request.get(f"{BASE}/ajaxs/jobs?page=2", headers=h)
    print("\n=== API halaman 2 lewat sesi browser ===")
    print("status:", r.status)
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        print(r.text()[:300])
        data = {}
    for k, v in data.items():
        if k != "data":
            print(f"  {k:<16} = {pendek(v, 120)}")
    items = data.get("data") or []
    print("jumlah lowongan:", len(items))
    if items:
        print("\n--- lowongan pertama, semua field ---")
        for k in sorted(items[0]):
            print(f"  {k:<24} = {pendek(items[0][k])}")

    # Halaman detail lowongan pertama dari daftar di halaman
    link = page.eval_on_selector_all(
        "a[href^='/']", "els => els.map(e => e.getAttribute('href'))"
        ".filter(h => h.split('/').length === 3)")
    if link:
        url = BASE + link[0]
        page.goto(url, timeout=40000, wait_until="networkidle")
        page.wait_for_timeout(2000)
        html = page.content()
        print("\n=== halaman detail ===")
        print("url:", url)
        print("ada JSON-LD JobPosting:", '"JobPosting"' in html)
        print("teks (1200 karakter):")
        print(page.inner_text("body")[:1200])

    browser.close()
