#!/usr/bin/env python3
"""Daftarkan jobindo.com ke registry. python pasang_jobindo.py"""
import ast, sys

BLOK = '''
# Jobindo.com: API Inertia.js partial-reload, ~197 loker.
from .jobindo_site import register_jobindo  # noqa: E402

register_jobindo()
'''

def main() -> None:
    path = "sites/companies.py"
    src = open(path, encoding="utf-8").read()
    if "register_jobindo" in src:
        print("jobindo sudah terdaftar, tidak ada yang diubah.")
        return
    for penanda in ("register_karircom()", "register_karirhub()", "register_glints()",
                    "register_kalibrr()", "register_dealls()", "register_kitalulus()"):
        if penanda in src:
            src = src.replace(penanda, penanda + "\n" + BLOK, 1)
            break
    else:
        sys.exit("Titik sisip tidak ketemu. Tambahkan manual di sites/companies.py:\n"
                 "from .jobindo_site import register_jobindo\nregister_jobindo()")
    ast.parse(src)
    open(path, "w", encoding="utf-8").write(src)
    print("jobindo didaftarkan.")

if __name__ == "__main__":
    main()
