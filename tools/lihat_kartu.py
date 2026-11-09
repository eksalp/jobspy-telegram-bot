#!/usr/bin/env python3
"""
Cetak HTML mentah di sekitar satu lowongan, dicari lewat TEKSNYA.

    python lihat_kartu.py <url> "<potongan judul>"
    python lihat_kartu.py https://magentaku.id/lowongan "Internship"

Berguna kalau kartunya tidak terdeteksi mode kandidat try_selector.py —
misalnya karena kartunya bukan <a> dan dibuka lewat modal JavaScript,
sehingga tidak punya URL sendiri.
"""

import re
import sys

sys.path.insert(0, ".")


def main() -> None:
    from bs4 import BeautifulSoup

    from sites.base import http_get

    url = sys.argv[1] if len(sys.argv) > 1 else "https://magentaku.id/lowongan"
    needle = sys.argv[2] if len(sys.argv) > 2 else "Internship"

    soup = BeautifulSoup(http_get(url).text, "html.parser")

    cocok = soup.find_all(string=re.compile(re.escape(needle), re.I))
    print(f"{len(cocok)} teks memuat '{needle}'\n")

    ditampilkan = 0
    for teks in cocok:
        node = teks.parent
        # naik sampai pembungkus yang isinya cukup untuk satu kartu
        for _ in range(6):
            if node.parent is None:
                break
            node = node.parent
            if 80 < len(node.get_text(" ", strip=True)) < 1200:
                break

        print("=" * 70)
        print(f"<{node.name} class={node.get('class')}>")
        print("-" * 70)
        print(node.prettify()[:1800])

        anchors = node.find_all("a", href=True)
        print(f"\nanchor di dalam ({len(anchors)}):")
        for a in anchors[:6]:
            print(f"   {a['href'][:80]}  <- {a.get_text(' ', strip=True)[:40]}")

        # atribut yang sering menyimpan id saat kartu dibuka lewat modal
        for attr in ("data-posting", "data-id", "data-bs-target", "onclick", "id"):
            nilai = node.get(attr)
            if nilai:
                print(f"   {attr} = {str(nilai)[:80]}")
        print()

        ditampilkan += 1
        if ditampilkan >= 2:
            break


if __name__ == "__main__":
    main()
