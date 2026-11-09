#!/usr/bin/env python3
"""Daftarkan toploker.com ke registry. python pasang_toploker.py"""
import ast, sys

BLOK = '''
# TopLoker: HTML statis, judul kartu terpotong tampilannya -- diambil dari
# slug URL, bukan span tampilan.
from .toploker_site import register_toploker  # noqa: E402

register_toploker()
'''

def main() -> None:
    path = "sites/companies.py"
    src = open(path, encoding="utf-8").read()
    if "register_toploker" in src:
        print("toploker sudah terdaftar, tidak ada yang diubah.")
        return
    for penanda in ("register_jobindo()", "register_karircom()", "register_karirhub()",
                    "register_glints()", "register_kalibrr()", "register_dealls()"):
        if penanda in src:
            src = src.replace(penanda, penanda + "\n" + BLOK, 1)
            break
    else:
        sys.exit("Titik sisip tidak ketemu. Tambahkan manual di sites/companies.py:\n"
                 "from .toploker_site import register_toploker\nregister_toploker()")
    ast.parse(src)
    open(path, "w", encoding="utf-8").write(src)
    print("toploker didaftarkan.")

if __name__ == "__main__":
    main()
