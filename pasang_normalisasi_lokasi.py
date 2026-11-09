#!/usr/bin/env python3
"""
Sambungkan normalize_location() ke make_record() di sites/base.py, supaya
SEMUA lowongan baru dari 23 adapter otomatis dapat kolom country+region —
tanpa perlu mengubah satu pun file adapter.

    python pasang_normalisasi_lokasi.py

Membuat cadangan sites/base.py.bak. Aman dijalankan berulang.
"""

import ast
import re
import shutil
import sys


def main() -> None:
    path = "sites/base.py"
    try:
        src = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        sys.exit(f"Tidak menemukan {path}. Jalankan dari root project.")

    if "normalize_location" in src:
        print("sites/base.py sudah terpasang normalisasi lokasi, "
             "tidak ada yang diubah.")
        return

    # 1) impor di bagian atas file
    if "from location_normalizer import normalize_location" not in src:
        # Sisipkan setelah baris impor lokal terakhir yang sudah ada
        # (categorize), supaya tetap mengikuti urutan impor lokal.
        pola = re.compile(
            r"(from categorize import[^\n]*\n)"
        )
        if pola.search(src):
            src = pola.sub(
                r"\1from location_normalizer import normalize_location\n",
                src, count=1,
            )
        else:
            sys.exit(
                "Tidak menemukan baris 'from categorize import ...' sebagai "
                "penanda tempat sisip. Tambahkan manual baris ini di dekat "
                "impor lain: from location_normalizer import normalize_location"
            )

    # 2) sisipkan pemanggilan di dalam make_record(), sebelum record dikembalikan
    pola_record = re.compile(
        r'(record = \{\n)', re.M
    )
    if not pola_record.search(src):
        sys.exit(
            "Tidak menemukan 'record = {' di make_record(). Struktur "
            "sites/base.py mungkin sudah berubah — sambungkan manual."
        )

    # Tambahkan country & region sebagai field di dalam dict record, tepat
    # setelah location diisi. Cara paling aman: proses SEBELUM dict dibuat,
    # lalu sisipkan dua key baru ke record setelah dict selesai dibangun.
    penanda_akhir_dict = re.compile(r"(\n    record\.update\(extra\)\n)")
    if not penanda_akhir_dict.search(src):
        sys.exit(
            "Tidak menemukan 'record.update(extra)' di make_record(). "
            "Sambungkan manual."
        )

    sisipan = (
        '\n'
        '    # Negara & region diturunkan dari `location` mentah, yang formatnya\n'
        '    # tidak konsisten antar 23 adapter (lihat location_normalizer.py\n'
        '    # untuk detail kenapa ini perlu). region cuma terisi kalau\n'
        '    # country == "Indonesia".\n'
        '    country, region = normalize_location(record.get("location"))\n'
        '    record["country"] = country\n'
        '    record["region"] = region\n'
    )
    src = penanda_akhir_dict.sub(r"\1" + sisipan, src, count=1)

    try:
        ast.parse(src)
    except SyntaxError as e:
        sys.exit(f"Hasil patch bermasalah di baris {e.lineno}: {e.msg}")

    shutil.copy(path, path + ".bak")
    open(path, "w", encoding="utf-8").write(src)

    print(f"{path} berhasil ditambal (cadangan: {path}.bak)")
    print("  country & region sekarang otomatis terisi untuk record baru")
    print("  sintaks: valid")


if __name__ == "__main__":
    main()
