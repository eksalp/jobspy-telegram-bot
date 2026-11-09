#!/usr/bin/env python3
"""
Diagnosa situs yang mengembalikan 0 loker.

    python diag.py samsung
    python diag.py wings

Bedanya dengan try_selector.py: script ini menembak endpoint yang persis
dipakai adapternya, lalu menampilkan data mentah yang benar-benar kembali —
supaya kelihatan apakah masalahnya di endpoint, di filter, atau di selector.
"""

from __future__ import annotations

import sys
from collections import Counter

sys.path.insert(0, ".")


def diag_workday(tenant: str, site: str, pod: str, scan: int = 400) -> None:
    """Tarik loker mentah tanpa filter lokasi, lalu rekap lokasinya."""
    from sites.base import http_post_json

    host = f"https://{tenant}.{pod}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{site}/jobs"
    print(f"Endpoint: {api}\n")

    locations: Counter = Counter()
    sample: list[tuple[str, str]] = []
    offset = 0

    while offset < scan:
        data = http_post_json(api, {
            "appliedFacets": {}, "limit": 20, "offset": offset, "searchText": "",
        }, headers={"Referer": f"{host}/en-US/{site}"})

        postings = data.get("jobPostings") or []
        if not postings:
            break
        if offset == 0:
            print(f"Total loker di tenant ini: {data.get('total')}\n")

        for p in postings:
            loc = p.get("locationsText") or "(kosong)"
            locations[loc] += 1
            if len(sample) < 5:
                sample.append((p.get("title", ""), loc))

        offset += len(postings)
        if offset >= (data.get("total") or 0):
            break

    print(f"Diperiksa {offset} loker. Lokasi paling sering:\n")
    for loc, n in locations.most_common(25):
        print(f"  {n:>4}x  {loc}")

    from sites.base import in_indonesia
    matched = {loc: n for loc, n in locations.items() if in_indonesia(loc)}
    print()
    if matched:
        print(f"✅ Cocok filter Indonesia: {sum(matched.values())} loker")
        for loc, n in matched.items():
            print(f"     {n:>4}x  {loc}")
    else:
        print("❌ Tidak ada lokasi yang cocok dengan filter Indonesia.")
        print("   Kalau di daftar di atas ada lokasi Indonesia yang tertulis")
        print("   dengan nama lain, tambahkan ke INDONESIA_HINTS di sites/base.py.")
        print("   Kalau memang tidak ada, tenant ini tidak memuat loker Indonesia")
        print("   dan Samsung sebaiknya dihapus saja dari registry.")


def diag_successfactors(base_url: str) -> None:
    """Lihat apa yang sebenarnya ada di halaman /search/ SuccessFactors."""
    from sites.base import get_soup

    base_url = base_url.rstrip("/")
    for path, params in [
        ("/search/", {"q": "", "sortColumn": "referencedate",
                      "sortOrder": "desc", "startrow": 0}),
        ("/search/", None),
        ("/", None),
    ]:
        url = base_url + path
        print(f"\n=== {url}  params={params}")
        try:
            soup = get_soup(url, params=params)
        except Exception as e:  # noqa: BLE001
            print(f"  gagal: {e}")
            continue

        for sel in ["a.jobTitle-link", "a[href*='/job/']",
                    "a[href*='job']", "a[href*='lowongan']",
                    "a[href*='career']", "a[href*='detail']"]:
            found = soup.select(sel)
            print(f"  {sel:<28} -> {len(found)}")
            for a in found[:3]:
                text = " ".join(a.get_text(" ", strip=True).split())[:70]
                print(f"        {text or '(tanpa teks)'}  [{a.get('href','')[:60]}]")

        title = soup.find("title")
        print(f"  <title>: {title.get_text(strip=True) if title else '(tidak ada)'}")



def diag_successfactors_modern(base_url: str) -> None:
    """Probe endpoint SuccessFactors Career Site Builder (CSB).

    CSB merender daftar loker lewat JavaScript, jadi selector generasi lama
    (a.jobTitle-link) tidak ketemu apa-apa. Tapi CSB umumnya masih menyediakan
    beberapa jalur non-JS: feed RSS, parameter paging, dan atribut
    data-careersite-propertyid di HTML.
    """
    import json
    import re

    from sites.base import http_get

    base_url = base_url.rstrip("/")
    candidates = [
        ("/rss", None),
        ("/search/", {"q": "", "startrow": 0, "ss": "paging"}),
        ("/search/", {"q": "", "startrow": 0, "locale": "bs_ID"}),
        ("/searchjobs", None),
        ("/go/All-Jobs/", None),
        ("/sitemap.xml", None),
    ]

    for path, params in candidates:
        url = base_url + path
        try:
            resp = http_get(url, params=params, retries=1, timeout=20)
        except Exception as e:  # noqa: BLE001
            print(f"  {path:<22} gagal ({type(e).__name__})")
            continue

        body = resp.text
        job_links = re.findall(r'href="([^"]*/job/[^"]+)"', body)
        rss_items = body.count("<item>")
        propids = body.count("data-careersite-propertyid")

        verdict = []
        if job_links:
            verdict.append(f"{len(job_links)} link /job/")
        if rss_items:
            verdict.append(f"{rss_items} item RSS")
        if propids:
            verdict.append(f"{propids} atribut careersite")
        print(f"  {path:<22} {resp.status_code}  "
              f"{', '.join(verdict) or 'tidak ada tanda lowongan'}")

        for link in job_links[:3]:
            print(f"        {link[:90]}")

    # cari JSON tertanam di halaman search
    print("\n  Mencari JSON tertanam di /search/ ...")
    try:
        body = http_get(f"{base_url}/search/", retries=1).text
    except Exception as e:  # noqa: BLE001
        print(f"    gagal: {e}")
        return

    for key in ["jobResults", "jobList", "searchResults", "jobs\":", "totalHits"]:
        if key in body:
            idx = body.index(key)
            print(f"    ditemukan '{key}' di posisi {idx}:")
            print(f"      ...{body[max(0, idx - 80):idx + 200]}...")
            break
    else:
        print("    tidak ada. Daftar loker kemungkinan diambil lewat XHR "
              "terpisah — cek tab Network di browser.")



def dump_around(url: str, href_contains: str, count: int = 2) -> None:
    """Cetak HTML mentah di sekitar link lowongan.

    Dipakai kalau deteksi judul otomatis terus meleset: lebih baik melihat
    struktur aslinya sekali daripada menebak berkali-kali.

        python diag.py dump
    """
    from bs4 import BeautifulSoup

    from sites.base import http_get

    html = http_get(url).text
    soup = BeautifulSoup(html, "html.parser")
    for chrome in soup.find_all(["nav", "header", "footer", "script", "style"]):
        chrome.decompose()

    anchors = soup.select(f'a[href*="{href_contains}"]')
    print(f"{len(anchors)} anchor cocok '{href_contains}'\n")

    seen = set()
    shown = 0
    for a in anchors:
        href = a.get("href")
        if href in seen:
            continue
        seen.add(href)

        node = a
        for _ in range(5):
            if node.parent is None:
                break
            node = node.parent
            if 60 < len(node.get_text(" ", strip=True)) < 6000:
                break

        print("=" * 70)
        print(f"anchor: {href}")
        print(f"pembungkus: <{node.name} class={node.get('class')}>")
        print("-" * 70)
        print(node.prettify()[:2200])
        print("\nSAUDARA SEBELUMNYA (kandidat judul):")
        sib = node.find_previous_sibling()
        for i in range(3):
            if sib is None:
                break
            text = " ".join(sib.get_text(" ", strip=True).split())[:90]
            print(f"  [{i}] <{sib.name} class={sib.get('class')}>  {text}")
            sib = sib.find_previous_sibling()
        print()

        shown += 1
        if shown >= count:
            break



TARGETS = {
    "samsung": lambda: diag_workday("sec", "Samsung_Careers", "wd3"),
    "kalbe": lambda: diag_workday("kalbe", "External", "wd102"),
    "wings": lambda: (diag_successfactors("https://www.wingscareer.com"),
                      diag_successfactors_modern("https://www.wingscareer.com")),
    "dump": lambda: dump_around(
        *(sys.argv[2:4] if len(sys.argv) >= 4
          else ("https://career.sinarmasland.com/vacancy-all", "jid="))),
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        sys.exit(
            f"Pakai: python diag.py [{' | '.join(TARGETS)}]\n"
            "  dump juga menerima URL dan pola href:\n"
            "    python diag.py dump <url> <bagian_href>\n"
            "    contoh: python diag.py dump https://situs.id/lowongan 'id='"
        )
    TARGETS[sys.argv[1]]()


if __name__ == "__main__":
    main()
