"""Diagnosa kenapa kolom Jobindo kosong di database.

    python cek_jobindo.py

Tempel SELURUH output-nya ke chat (sebagai teks).
"""
from jobindo import search_jobindo, jobindo_to_records
import sites

jobs = search_jobindo("semua", limit=3)
print("jumlah mentah dari API:", len(jobs))
if jobs:
    j = jobs[0]
    print("kunci mentah:", sorted(j.keys()))
    print("region_name  :", repr(j.get("region_name")))
    print("created_at   :", repr(j.get("created_at")))
    print("ada html?    :", bool(j.get("html")), "| ada message?:", bool(j.get("message")))
    r = jobindo_to_records(jobs[:1], "semua", None, "")[0]
    print("record.location   :", repr(r.get("location")))
    print("record.description:", repr((r.get("description") or "")[:80]))

spec = sites.get("jobindo")
print("fetch terdaftar dari modul:", spec.fetch.__module__, "|", spec.fetch.__qualname__)
hasil = sites.run(spec, query="semua", limit=2, chat_id="cek")
for h in hasil:
    print("run ->", h["location"], "|", h["date_posted"], "|", (h["description"] or "")[:60])
