#!/usr/bin/env python3
"""
Uji CSS selector terhadap satu halaman, tanpa perlu mendaftarkannya dulu di
companies.py. Gunanya supaya iterasi selector cepat: ubah, jalankan, lihat.

Contoh:

    python try_selector.py https://career.indofood.com \\
        --card "div.card.card-job.p-3" \\
        --title "h5" --location ".location"

Kalau --card tidak diisi, script akan menampilkan kandidat pembungkus berulang
yang ditemukan di halaman itu, lengkap dengan contoh isinya — jadi kamu bisa
memilih sendiri mana yang benar.

    python try_selector.py https://career.indofood.com

Tambahkan --html untuk mencetak HTML mentah satu kartu pertama, berguna kalau
selector judul/lokasi masih meleset.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ModuleNotFoundError as e:
    sys.exit(f"Butuh paket: {e.name}. Jalankan: pip install requests beautifulsoup4")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _anchor(node, selector=None):
    """Cari <a> untuk satu kartu.

    Sebagian situs (MagangHub) menjadikan kartunya SENDIRI sebagai <a>, bukan
    membungkus <a> di dalamnya. Tanpa pemeriksaan ini, kartu seperti itu
    dilaporkan "tidak punya link" padahal justru linknya ada di elemen kartu.
    """
    if selector:
        return node.select_one(selector)
    if node.name == "a" and node.get("href"):
        return node
    return node.find("a", href=True)


def clean(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True))


def show_candidates(soup: BeautifulSoup, limit: int = 12) -> None:
    """Daftar semua tanda tangan elemen yang berulang >=2 kali, urut terbanyak."""
    for chrome in soup.find_all(["nav", "header", "footer", "aside"]):
        chrome.decompose()

    counter: Counter = Counter()
    example: dict[str, object] = {}

    for tag in soup.find_all(True):
        classes = tag.get("class") or []
        if not classes:
            continue
        sig = tag.name + "".join(f".{c}" for c in classes[:3])
        text = clean(tag)
        # kartu loker biasanya punya teks, tapi tidak sepanjang seluruh halaman
        if not (10 < len(text) < 400):
            continue
        counter[sig] += 1
        example.setdefault(sig, tag)

    print("Kandidat pembungkus berulang (urut jumlah kemunculan):\n")
    shown = 0
    for sig, count in counter.most_common(60):
        if count < 2:
            continue
        node = example[sig]
        has_link = node.find("a", href=True) is not None
        mark = "🔗" if has_link else "  "
        print(f"{mark} {count:>3}x  {sig}")
        print(f"        {clean(node)[:120]}")
        shown += 1
        if shown >= limit:
            break

    if not shown:
        print("  (tidak ada — halaman ini mungkin SPA, isinya dirender JavaScript)")
    else:
        print("\n🔗 = mengandung link, kandidat kuat untuk kartu loker.")
        print("Pilih satu, lalu jalankan ulang dengan --card \"<selector>\"")


def test_selectors(soup: BeautifulSoup, base_url: str, args) -> None:
    cards = soup.select(args.card)
    print(f"Selector kartu : {args.card}")
    print(f"Kartu ditemukan: {len(cards)}\n")

    if not cards:
        print("Tidak ada yang cocok. Jalankan tanpa --card untuk lihat kandidat lain.")
        return

    for i, node in enumerate(cards[: args.limit], 1):
        a = _anchor(node, args.link)
        url = urljoin(base_url, a["href"]) if a and a.get("href") else None

        title = None
        if args.title:
            found = node.select_one(args.title)
            title = clean(found) if found else None
        if not title and a:
            title = clean(a)

        loc = None
        if args.location:
            found = node.select_one(args.location)
            loc = clean(found) if found else None

        print(f"[{i}] judul : {title or '(TIDAK KETEMU)'}")
        print(f"    lokasi: {loc or '(tidak diisi/ketemu)'}")
        print(f"    url   : {url or '(TIDAK KETEMU)'}")

    if args.html and cards:
        print("\n--- HTML kartu pertama ---")
        print(cards[0].prettify()[:2500])

    # penilaian ringkas
    print()
    urls, titles, with_url = [], [], 0
    for node in cards:
        a = _anchor(node, args.link)
        if a and a.get("href"):
            with_url += 1
            urls.append(urljoin(base_url, a["href"]))
        found = node.select_one(args.title) if args.title else a
        if found:
            titles.append(clean(found))

    problems = []
    if with_url < len(cards) * 0.6:
        problems.append(f"hanya {with_url}/{len(cards)} kartu punya link")

    # Semua kartu menunjuk URL yang sama = ini bukan daftar lowongan.
    # Contoh nyata: panel "View Similar Job" di halaman detail.
    if len(urls) > 1 and len(set(urls)) == 1:
        problems.append("SEMUA kartu menunjuk URL yang sama "
                        f"({urls[0][:70]}) — ini kemungkinan panel terkait, "
                        "bukan daftar lowongan")

    # Judul seragam = tombol berulang, bukan nama posisi.
    # Contoh nyata: "Selengkapnya +" di kartu kategori.
    if len(titles) > 1 and len(set(titles)) == 1:
        problems.append(f'SEMUA judul sama ("{titles[0][:40]}") — '
                        "kemungkinan teks tombol, bukan judul lowongan")

    generic = {"selengkapnya", "read more", "lihat", "view", "detail",
               "lihat detail", "selengkapnya +", "view similar job", "apply"}
    if titles and sum(1 for t in titles if t.strip().lower() in generic) > len(titles) / 2:
        problems.append("mayoritas judul berupa teks tombol generik")

    if problems:
        print("⚠️  Selector ini kemungkinan SALAH:")
        for p in problems:
            print(f"    - {p}")
        print("    Jalankan tanpa --card untuk lihat kandidat lain, atau cari "
              "halaman listing yang benar.")
    else:
        print(f"✅ {with_url}/{len(cards)} kartu punya link, "
              f"{len(set(titles))} judul unik — selector tampak benar.")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Uji CSS selector kartu loker terhadap satu halaman.")
    p.add_argument("url")
    p.add_argument("--card", help="selector kartu loker")
    p.add_argument("--title", help="selector judul di dalam kartu")
    p.add_argument("--location", help="selector lokasi di dalam kartu")
    p.add_argument("--link", help="selector <a> di dalam kartu (default: <a> pertama)")
    p.add_argument("--limit", type=int, default=5, help="jumlah kartu ditampilkan")
    p.add_argument("--html", action="store_true",
                   help="cetak HTML mentah kartu pertama")
    args = p.parse_args()

    try:
        html = fetch(args.url)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Gagal mengambil halaman: {e}")

    soup = BeautifulSoup(html, "html.parser")

    if args.card:
        test_selectors(soup, args.url, args)
    else:
        show_candidates(soup)


if __name__ == "__main__":
    main()
