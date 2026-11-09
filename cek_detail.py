"""Cari sumber deskripsi untuk Karir.com dan Glints.

    python cek_detail.py

Hanya membaca, tidak mengubah database. Tempel SELURUH output-nya ke chat.
"""
import html as html_lib
import json
import re
import time

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def pendek(v, n=250):
    t = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return t if len(t) <= n else t[:n] + "...(dipotong)"


def cari_kunci(obj, pola=re.compile(r"desc|requirement|qualif|responsib", re.I),
               jalur="", hasil=None, maks=15):
    """Daftar jalur JSON yang namanya mirip deskripsi."""
    hasil = [] if hasil is None else hasil
    if len(hasil) >= maks:
        return hasil
    if isinstance(obj, dict):
        for k, v in obj.items():
            j = f"{jalur}.{k}" if jalur else k
            if pola.search(k) and isinstance(v, str) and len(v) > 30:
                hasil.append((j, v))
            cari_kunci(v, pola, j, hasil, maks)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            cari_kunci(v, pola, f"{jalur}[{i}]", hasil, maks)
    return hasil


def json_dari_html(teks):
    for pola in (r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                 r'data-page="([^"]*)"'):
        m = re.search(pola, teks, re.S)
        if m:
            try:
                return json.loads(html_lib.unescape(m.group(1)))
            except json.JSONDecodeError:
                pass
    return None


def coba(label, fn):
    try:
        r = fn()
        ct = r.headers.get("content-type", "")
        print(f"  [{label}] status {r.status_code} | {ct[:40]}")
        data = None
        if "json" in ct:
            data = r.json()
        elif r.status_code == 200:
            data = json_dari_html(r.text)
            print(f"      JSON tertanam di HTML: {bool(data)}")
            if not data and "descriptionJsonString" in r.text:
                print("      (teks 'descriptionJsonString' ada di HTML)")
        if data is not None:
            temuan = cari_kunci(data)
            if not temuan:
                print("      tidak ada kunci mirip deskripsi. Kunci teratas:",
                      pendek(list(data)[:20] if isinstance(data, dict) else type(data).__name__))
            for jalur, isi in temuan:
                print(f"      {jalur} = {pendek(isi)}")
    except Exception as e:  # noqa: BLE001
        print(f"  [{label}] GAGAL: {str(e)[:150]}")
    time.sleep(1.1)  # karir.com minta crawl-delay 1 detik


# ---------------------------------------------------------------- Karir.com
print("=================== KARIR.COM ===================")
try:
    from karircom import DETAIL_URL, _HEADERS, search_karircom
    opp = search_karircom("semua", limit=1)[0]
    oid = opp.get("id")
    print("kunci listing:", sorted(opp))
    for k in ("id", "slug", "url", "opportunity_url", "job_title", "title"):
        if k in opp:
            print(f"  {k} = {pendek(opp[k], 120)}")
    h = {**_HEADERS, "User-Agent": UA}
    hh = {"User-Agent": UA}
    coba("GET detail?id", lambda: requests.get(DETAIL_URL, params={"id": oid}, headers=h, timeout=20))
    coba("GET detail?opportunity_id", lambda: requests.get(DETAIL_URL, params={"opportunity_id": oid}, headers=h, timeout=20))
    coba("GET detail/{id}", lambda: requests.get(f"{DETAIL_URL}/{oid}", headers=h, timeout=20))
    coba("POST detail {id}", lambda: requests.post(DETAIL_URL, json={"id": oid}, headers=h, timeout=20))
    coba("POST detail {opportunity_id}", lambda: requests.post(DETAIL_URL, json={"opportunity_id": oid}, headers=h, timeout=20))
    for pola in ("https://karir.com/opportunities/{}", "https://karir.com/lowongan/{}"):
        u = pola.format(oid)
        coba(f"HTML {u}", lambda u=u: requests.get(u, headers=hh, timeout=20))
except Exception as e:  # noqa: BLE001
    print("Karir.com gagal total:", e)

# ---------------------------------------------------------------- Glints
print("\n=================== GLINTS ===================")
try:
    from glints import glints_to_records, search_glints
    jobs = search_glints("semua", limit=1)
    job = jobs[0]
    print("kunci listing:", sorted(job))
    url = glints_to_records(jobs, "semua", None, "")[0]["job_url"]
    print("url:", url)
    coba("HTML detail", lambda: requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=20))
except Exception as e:  # noqa: BLE001
    print("Glints gagal total:", e)
