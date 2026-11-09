#!/usr/bin/env python3
"""
Deteksi platform ATS tiap situs karir, lalu cetak baris registrasi yang tinggal
di-copy ke sites/companies.py.

Jalankan dari mesinmu sendiri (bukan dari sandbox), karena butuh akses internet
bebas:

    python detect_ats.py                # semua situs di PENDING
    python detect_ats.py gojek nestle   # hanya situs tertentu
    python detect_ats.py --all          # termasuk yang sudah terkonfigurasi

Yang dilakukan script ini per situs:
  1. GET halaman karirnya (ikuti redirect)
  2. Cari sidik jari platform di HTML final + URL akhir
  3. Kalau ketemu platform ber-API, tarik token/tenant-nya dari URL
  4. Uji endpoint API-nya sungguhan dan laporkan berapa loker yang kembali
  5. Cetak baris `register_*(...)` yang siap dipakai

Kalau platform tidak terdeteksi, script tetap melaporkan petunjuk yang berguna:
apakah halamannya butuh JavaScript, ada berapa link mirip-lowongan, dan apakah
ada XHR ke endpoint /api/ yang kelihatan di HTML.
"""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import urljoin, urlparse

try:
    import requests
except ModuleNotFoundError:
    sys.exit("Butuh paket `requests`. Jalankan: pip install requests")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
}

TIMEOUT = 25


# --------------------------------------------------------------------------- #
# Sidik jari platform
# --------------------------------------------------------------------------- #
FINGERPRINTS = [
    ("workday",         [r"myworkdayjobs\.com", r"wday/cxs"]),
    ("greenhouse",      [r"boards\.greenhouse\.io", r"greenhouse\.io/embed",
                         r"job-boards\.greenhouse\.io"]),
    ("lever",           [r"jobs\.lever\.co", r"api\.lever\.co"]),
    ("smartrecruiters", [r"smartrecruiters\.com"]),
    ("ashby",           [r"jobs\.ashbyhq\.com", r"ashbyhq\.com/posting-api"]),
    ("successfactors",  [r"successfactors\.(?:com|eu)", r"jobTitle-link",
                         r"sfcareer", r"careersection"]),
    ("taleo",           [r"taleo\.net", r"tbe\.taleo\.net"]),
    ("phenom",          [r"phenompeople", r"ph_widget", r"phApp\s*=",
                         r"ddoKey", r"phenom\.cloud"]),
    ("icims",           [r"icims\.com"]),
    ("oracle_hcm",      [r"oraclecloud\.com/hcmUI", r"/hcmRestApi/"]),
    ("talentics",       [r"talentics\.id"]),
    ("darwinbox",       [r"darwinbox\.(?:in|com)"]),
    ("jobstreet",       [r"jobstreet\.co\.id"]),
]

# Cara menarik token/tenant dari URL yang ditemukan di halaman
TOKEN_PATTERNS = {
    "workday": r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[\w-]+/)?([\w-]+)",
    "greenhouse": r"greenhouse\.io/(?:embed/job_board\?for=|boards/)?([\w-]+)",
    "lever": r"lever\.co/([\w-]+)",
    "smartrecruiters": r"smartrecruiters\.com/(?:v1/companies/)?([\w-]+)",
    "ashby": r"ashbyhq\.com/([\w-]+)",
}


def detect(url: str) -> dict:
    result: dict = {"url": url, "platform": None, "final_url": None,
                    "hints": [], "config": None, "job_count": None}
    # Beberapa situs hanya melayani https, atau host `www.`-nya berbeda.
    # Coba beberapa varian sebelum menyerah.
    candidates = [url]
    if url.startswith("http://"):
        candidates.append("https://" + url[len("http://"):])
    for cand in list(candidates):
        host = urlparse(cand).netloc
        if host and not host.startswith("www."):
            candidates.append(cand.replace(f"//{host}", f"//www.{host}", 1))

    resp = None
    errors = []
    for cand in candidates:
        try:
            resp = requests.get(cand, headers=HEADERS, timeout=TIMEOUT,
                                allow_redirects=True)
            break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{cand}: {type(e).__name__}")

    if resp is None:
        result["hints"].append("gagal diakses -> " + "; ".join(errors))
        return result

    html = resp.text
    result["html"] = html
    result["final_url"] = resp.url
    result["status"] = resp.status_code

    haystack = f"{resp.url}\n{html}"

    for platform, patterns in FINGERPRINTS:
        if any(re.search(p, haystack, re.I) for p in patterns):
            result["platform"] = platform
            break

    # tarik token/tenant
    if result["platform"] in TOKEN_PATTERNS:
        m = re.search(TOKEN_PATTERNS[result["platform"]], haystack, re.I)
        if m:
            result["config"] = m.groups()

    # petunjuk tambahan kalau tidak terdeteksi
    if not result["platform"]:
        job_links = len(re.findall(
            r'href="[^"]*(?:job|career|lowongan|vacanc|position)[^"]*"', html, re.I))
        result["hints"].append(f"{job_links} link mirip-lowongan di HTML")

        if len(re.sub(r"<[^>]+>", "", html).strip()) < 2000:
            result["hints"].append("HTML hampir kosong → kemungkinan SPA, butuh Playwright")

        apis = set(re.findall(r'["\'](/(?:api|_next/data|graphql)[^"\']{3,60})["\']', html))
        for api in list(apis)[:5]:
            result["hints"].append(f"endpoint kandidat: {api}")

        if re.search(r"login|masuk|sign\s*in", html[:4000], re.I):
            result["hints"].append("halaman depan tampak butuh login")

        # Platform tidak dikenal -> cari dulu halaman daftar lowongannya,
        # baru simpulkan selector dari sana.
        try:
            from selector_infer import infer_selectors
            listing_url, listing_html = find_listing_page(resp.url, html)
            if listing_url.rstrip("/") != resp.url.rstrip("/"):
                result["listing_url"] = listing_url
                result["hints"].append(f"halaman listing: {listing_url}")
            result["selectors"] = infer_selectors(listing_html)
        except ModuleNotFoundError:
            result["hints"].append(
                "pasang beautifulsoup4 untuk dapat tebakan selector otomatis")
        except Exception as e:  # noqa: BLE001
            result["hints"].append(f"inferensi selector gagal: {e}")

    return result


# --------------------------------------------------------------------------- #
# Verifikasi endpoint API sungguhan
# --------------------------------------------------------------------------- #
def verify(platform: str, cfg: tuple) -> tuple[int | None, str | None]:
    """Return (jumlah_loker, pesan_error)."""
    try:
        if platform == "workday":
            tenant, pod, site = cfg
            api = f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
            r = requests.post(api, json={"appliedFacets": {}, "limit": 20,
                                         "offset": 0, "searchText": ""},
                              headers={**HEADERS, "Content-Type": "application/json"},
                              timeout=TIMEOUT)
            r.raise_for_status()
            return r.json().get("total", 0), None

        if platform == "greenhouse":
            r = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{cfg[0]}/jobs",
                headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return len(r.json().get("jobs", [])), None

        if platform == "lever":
            r = requests.get(f"https://api.lever.co/v0/postings/{cfg[0]}",
                             params={"mode": "json"}, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return len(r.json()), None

        if platform == "smartrecruiters":
            r = requests.get(
                f"https://api.smartrecruiters.com/v1/companies/{cfg[0]}/postings",
                params={"limit": 10}, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json().get("totalFound", 0), None

        if platform == "ashby":
            r = requests.get(
                f"https://api.ashbyhq.com/posting-api/job-board/{cfg[0]}",
                headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return len(r.json().get("jobs", [])), None
        # Platform berbasis HTML: hitung anchor lowongan di halaman listing.
        if platform in {"successfactors", "talentics", "darwinbox", "phenom"}:
            url = cfg[0] if cfg else None
            if not url:
                return None, "tidak ada URL untuk diverifikasi"
            paths = {
                "successfactors": ["/search/?q=&startrow=0", "/search/"],
                "talentics": ["/jobs", "/"],
                "darwinbox": ["/ms/candidate/careers", "/careers", "/"],
                "phenom": ["/search", "/jobs", "/"],
            }[platform]
            for path in paths:
                try:
                    r = requests.get(url.rstrip("/") + path, headers=HEADERS,
                                     timeout=TIMEOUT, allow_redirects=True)
                    n = _count_job_anchors(r.text)
                    if n:
                        return n, None
                except Exception:  # noqa: BLE001
                    continue
            return None, "halaman listing tidak mengembalikan lowongan"

    except Exception as e:  # noqa: BLE001
        return None, str(e)

    return None, "platform tidak punya verifier"


# --------------------------------------------------------------------------- #
# Cetak baris registrasi siap-copy
# --------------------------------------------------------------------------- #
def emit(name: str, label: str, company: str, industry: str,
         url: str, res: dict) -> str:
    platform, cfg = res["platform"], res["config"]

    if platform == "workday" and cfg:
        tenant, pod, site = cfg
        return (
            f'register_workday(\n'
            f'    name="{name}", label="{label}", company="{company}",\n'
            f'    tenant="{tenant}", site="{site}", pod="{pod}",\n'
            f'    industry="{industry}",\n'
            f'    company_url_direct="{url}",\n'
            f'    verified=True, tags={{"id"}},\n'
            f')'
        )

    if platform in {"greenhouse", "lever", "smartrecruiters", "ashby"} and cfg:
        return (
            f'register_ats(\n'
            f'    "{platform}", name="{name}", label="{label}", company="{company}",\n'
            f'    token="{cfg[0]}",\n'
            f'    industry="{industry}",\n'
            f'    company_url_direct="{url}",\n'
            f'    verified=True, tags={{"id"}},\n'
            f')'
        )

    if platform == "phenom":
        host = f"{urlparse(res['final_url'] or url).scheme}://" \
               f"{urlparse(res['final_url'] or url).netloc}"
        return (
            f'register_phenom(\n'
            f'    name="{name}", label="{label}", company="{company}",\n'
            f'    host="{host}", country="id",\n'
            f'    selected_fields={{"country": ["Indonesia"]}},\n'
            f'    industry="{industry}",\n'
            f'    company_url_direct="{url}",\n'
            f'    tags={{"id"}},\n'
            f')'
        )

    if platform == "successfactors":
        host = f"{urlparse(res['final_url'] or url).scheme}://" \
               f"{urlparse(res['final_url'] or url).netloc}"
        return (
            f'register_html(\n'
            f'    "successfactors", name="{name}", label="{label}", company="{company}",\n'
            f'    base_url="{host}",\n'
            f'    industry="{industry}",\n'
            f'    company_url_direct="{url}",\n'
            f'    tags={{"id"}},\n'
            f')'
        )

    # Platform tidak dikenal: pakai selector hasil inferensi DOM kalau ada.
    sel = res.get("selectors") or {}
    kind = "playwright" if any("SPA" in h for h in res["hints"]) else "static"

    def q(value, placeholder):
        if value:
            return f'"{value}",'
        return f'"{placeholder}",  # <- belum ketebak, isi manual'

    header = f'# {label} — platform tidak dikenal'
    if sel.get("card"):
        header += f'\n# Selector ditebak dari struktur DOM, keyakinan: {sel["confidence"]}'
        for s in sel.get("samples", [])[:2]:
            header += f'\n#   contoh kartu: {s[:110]}'
        header += '\n# Cek dulu hasilnya sebelum dipercaya penuh.'
    else:
        header += f'\n# Tidak ada struktur berulang yang terdeteksi ({sel.get("confidence", "-")}).'
        header += f'\n# Buka {url}, klik kanan satu kartu loker > Inspect, isi manual.'

    lines = [
        header,
        'register_html(',
        f'    "{kind}", name="{name}", label="{label}", company="{company}",',
        f'    list_url="{res.get("listing_url") or res["final_url"] or url}",',
        f'    card={q(sel.get("card"), "ISI_SELECTOR_KARTU")}',
        f'    title={q(sel.get("title"), "ISI_SELECTOR_JUDUL")}',
    ]
    if sel.get("location"):
        lines.append(f'    location="{sel["location"]}",')
    if sel.get("level"):
        lines.append(f'    level="{sel["level"]}",')
    lines += [
        f'    industry="{industry}",',
        f'    company_url_direct="{url}",',
        '    tags={"id"},',
        ')',
    ]
    return "\n".join(lines)


def _load_pending() -> dict:
    """Muat sites/pending.py langsung dari path, bukan lewat `import sites`.

    Kalau diimpor sebagai paket, `sites/__init__.py` ikut jalan dan menarik
    seluruh rantai adapter (bs4, playwright, jobspy, scraper lama). Detektor
    tidak butuh semua itu — cukup daftar URL-nya.
    """
    import importlib.util

    # File ini ada di tools/, tapi sites/pending.py ada di root project —
    # jadi naik satu folder dulu (dirname dua kali), bukan cari sites/ di
    # sebelah file ini sendiri.
    root_project = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root_project, "sites", "pending.py")
    if not os.path.exists(path):
        sys.exit(
            f"Tidak menemukan {path}\n"
            "Jalankan skrip ini dari mana saja — ia mencari sites/pending.py "
            "satu folder di atas tools/ secara otomatis."
        )
    spec = importlib.util.spec_from_file_location("_pending", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PENDING


# --------------------------------------------------------------------------- #
# Cari halaman daftar lowongan yang sebenarnya
# --------------------------------------------------------------------------- #
LISTING_LINK = re.compile(
    r"(lowongan|vacanc|vacancy|opening|job\s*list|daftar\s*lowongan|"
    r"posisi|position|karir|karier|career|opportunit|peluang|rekrutmen|"
    r"recruitment|see\s*all|lihat\s*semua|explore)",
    re.I,
)


def _count_job_anchors(html: str) -> int:
    """Hitung anchor mirip-lowongan, di luar nav/header/footer."""
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError:
        return len(re.findall(r'href="[^"]*(?:job|lowongan|vacanc)[^"]*"', html, re.I))

    soup = BeautifulSoup(html, "html.parser")
    for chrome in soup.find_all(["nav", "header", "footer", "aside"]):
        chrome.decompose()

    # Pola HARUS menunjuk ke satu lowongan tertentu, bukan sekadar memuat kata
    # "career". Pola longgar sebelumnya membuat 9 link pemilih bahasa di
    # wingscareer.com terhitung sebagai 12 lowongan.
    detail = re.compile(
        r"(/job/|/jobs/|/vacancy|/vacancies/|/lowongan/|/karir/detail|"
        r"/career(?:s)?/(?:detail|view)|job[_-]?id=|jobid=|vacancy[_-]?id=)",
        re.I,
    )
    # link yang cuma ganti bahasa / urutan / halaman bukan lowongan
    noise = re.compile(r"([?&](locale|lang|sortColumn|sortOrder|startrow|page)=)", re.I)

    count = 0
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not detail.search(href) or noise.search(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        count += 1
    return count


def find_listing_page(start_url: str, html: str, budget: int = 4) -> tuple[str, str]:
    """Dari halaman depan, ikuti link yang tampak menuju daftar lowongan.

    Halaman depan situs karir biasanya cuma landing page — lowongannya satu
    klik lagi ke dalam. Tanpa langkah ini, inferensi selector cuma menemukan
    menu navigasi, karena itulah satu-satunya struktur berulang di sana.

    Return (url_terbaik, html_terbaik).
    """
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError:
        return start_url, html

    best_url, best_html = start_url, html
    best_score = _count_job_anchors(html)

    soup = BeautifulSoup(html, "html.parser")
    seen = {start_url.rstrip("/")}
    candidates = []

    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        if not (LISTING_LINK.search(text) or LISTING_LINK.search(href)):
            continue
        full = urljoin(start_url, href)
        if urlparse(full).netloc != urlparse(start_url).netloc:
            continue
        if full.rstrip("/") in seen:
            continue
        seen.add(full.rstrip("/"))
        # link yang teksnya cocok lebih menjanjikan daripada yang cuma href-nya
        priority = 0 if LISTING_LINK.search(text) else 1
        candidates.append((priority, full))

    for _, cand in sorted(candidates)[:budget]:
        try:
            r = requests.get(cand, headers=HEADERS, timeout=TIMEOUT,
                             allow_redirects=True)
            score = _count_job_anchors(r.text)
        except Exception:  # noqa: BLE001
            continue
        if score > best_score:
            best_url, best_html, best_score = r.url, r.text, score

    return best_url, best_html


def main() -> None:
    PENDING = _load_pending()

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    targets = {k: v for k, v in PENDING.items() if not args or k in args}

    print(f"Memeriksa {len(targets)} situs...\n")
    summary: dict[str, list[str]] = {}
    snippets: list[str] = []

    for name, (label, url, company, industry) in targets.items():
        res = detect(url)
        platform = res["platform"] or "tidak terdeteksi"

        count = None
        cfg = res["config"]
        if not cfg and res["platform"] in {"successfactors", "talentics",
                                           "darwinbox", "phenom"}:
            parsed = urlparse(res["final_url"] or url)
            cfg = (f"{parsed.scheme}://{parsed.netloc}",)
        if cfg:
            count, err = verify(res["platform"], cfg)
            if err:
                res["hints"].append(f"verifikasi API gagal: {err}")

        sel = res.get("selectors") or {}
        if count:
            badge, detail = "OK ", f"{count} loker"
        elif sel.get("card"):
            badge = "~~ "
            detail = f'selector ditebak: {sel["card"]}  [{sel["confidence"]}]'
        else:
            badge = "?? "
            detail = ", ".join(res["hints"][:2]) or "-"
        print(f"{badge}{name:<14} {platform:<16} {detail}")

        # URL listing harus selalu tampil. Sebelumnya ia hanya muncul lewat
        # hints, dan hints tidak dicetak kalau selector berhasil ditebak —
        # akibatnya justru situs yang berhasil malah menyembunyikan URL yang
        # paling dibutuhkan untuk mengujinya.
        if res.get("listing_url"):
            print(f"   {'':<14} {'':<16} listing: {res['listing_url']}")

        summary.setdefault(platform, []).append(name)
        snippets.append(f"# --- {label} ({url})\n"
                        + emit(name, label, company, industry, url, res))

    print("\n" + "=" * 70)
    print("RINGKASAN PLATFORM")
    print("=" * 70)
    for platform, group in sorted(summary.items(), key=lambda kv: -len(kv[1])):
        print(f"  {platform:<18} {len(group):>2} situs: {', '.join(group)}")

    out = "generated_sites.py"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# Dihasilkan oleh detect_ats.py — review dulu, "
                 "lalu pindahkan ke sites/companies.py\n\n")
        fh.write("\n\n".join(snippets) + "\n")

    print(f"\nBaris registrasi siap-copy ditulis ke: {out}")
    print("Review dulu isinya, baru pindahkan ke sites/companies.py")


if __name__ == "__main__":
    main()
