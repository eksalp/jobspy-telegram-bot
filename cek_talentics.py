"""Diagnosa Talentics: kenapa bot cuma dapat 1 lowongan.

    python cek_talentics.py

Hanya membaca, tidak mengubah database. Tempel SELURUH output-nya ke chat.
"""
import json

import requests
from playwright.sync_api import sync_playwright

BASE = "https://jobs.talentics.id"

print("=== robots.txt ===")
try:
    r = requests.get(f"{BASE}/robots.txt", timeout=15)
    print("status", r.status_code)
    print(r.text[:800])
except Exception as e:  # noqa: BLE001
    print("gagal:", e)

api = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    def catat(resp):
        ct = resp.headers.get("content-type", "")
        if "json" in ct and resp.request.resource_type in ("xhr", "fetch"):
            try:
                body = resp.text()
            except Exception:  # noqa: BLE001
                body = ""
            api.append((resp.request.method, resp.url, resp.status, body[:400]))

    page.on("response", catat)
    page.goto(f"{BASE}/jobs", timeout=40000, wait_until="networkidle")
    page.wait_for_timeout(4000)

    print("\n=== halaman ===")
    print("url akhir :", page.url)
    print("judul     :", page.title())

    print("\n=== jumlah elemen per selector lama ===")
    for sel in ["[class*='job-card']", "[class*='job-item']",
                "[class*='vacancy']", "a[href*='/jobs/']"]:
        print(f"  {sel:<24} {page.locator(sel).count()}")

    print("\n=== semua link (maks 40) ===")
    links = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => [e.getAttribute('href'), e.innerText.trim().slice(0,60)])")
    for href, teks in links[:40]:
        print(f"  {href}  |  {teks!r}")

    print("\n=== teks halaman (800 karakter pertama) ===")
    print(page.inner_text("body")[:800])

    print("\n=== request API (JSON) yang dipanggil halaman ===")
    for m, u, s, b in api[:15]:
        print(f"  {m} {s} {u}")
        print(f"     {b[:300]}")

    browser.close()
