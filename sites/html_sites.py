from __future__ import annotations

"""
Adapter untuk situs yang tidak punya API JSON rapi.

Tiga jenis:
  1. SAP SuccessFactors  — HTML listing dengan struktur seragam antar tenant
  2. static HTML         — digerakkan konfigurasi CSS selector (tanpa nulis kode)
  3. Playwright          — untuk SPA yang butuh JS dirender dulu

Prinsipnya: pola scraping-nya dideskripsikan sebagai data (selector), bukan
kode baru per situs. Jadi kalau layout situs berubah, yang diedit cuma satu
baris selector di companies.py.
"""

import re
from urllib.parse import urljoin

from .base import HEADERS, get_soup, is_browse_all, matches, strip_html
from .registry import SiteSpec, register


# --------------------------------------------------------------------------- #
# 1. SAP SuccessFactors
# --------------------------------------------------------------------------- #
def successfactors_fetcher(base_url: str, page_size: int = 25):
    """base_url contoh: https://karir.contoh.com  (halaman /search-nya)."""
    base_url = base_url.rstrip("/")

    def fetch(query: str, limit: int) -> list[dict]:
        jobs: list[dict] = []
        startrow = 0
        q = "" if is_browse_all(query) else query.strip()

        while len(jobs) < limit and startrow < 500:
            soup = get_soup(f"{base_url}/search/", params={
                "q": q,
                "sortColumn": "referencedate",
                "sortOrder": "desc",
                "startrow": startrow,
            })
            links = soup.select("a.jobTitle-link, a[href*='/job/']")
            if not links:
                break

            for link in links:
                href = link.get("href") or ""
                row = link.find_parent("tr") or link.find_parent("li") or link.parent
                loc_tag = row.select_one(".jobLocation, .job-location") if row else None
                dept_tag = row.select_one(".jobDepartment, .job-department") if row else None
                jobs.append({
                    "title": link.get_text(strip=True),
                    "url": urljoin(base_url, href),
                    "job_id": href,
                    "location": loc_tag.get_text(strip=True) if loc_tag else None,
                    "job_function": dept_tag.get_text(strip=True) if dept_tag else None,
                })
                if len(jobs) >= limit:
                    break

            if len(links) < page_size:
                break
            startrow += page_size

        return jobs[:limit]

    return fetch


# --------------------------------------------------------------------------- #
# 2. Static HTML digerakkan selector
# --------------------------------------------------------------------------- #
def static_html_fetcher(
    list_url: str,
    card: str,
    title: str | None = None,
    link: str | None = None,
    location: str | None = None,
    function: str | None = None,
    level: str | None = None,
    base_url: str | None = None,
    page_param: str | None = None,
    page_start: int = 1,
    max_pages: int = 10,
    extra_params: dict | None = None,
):
    """Scraper HTML statis yang seluruh perilakunya ditentukan CSS selector.

    card      selector untuk tiap kartu loker
    title     selector judul di dalam kartu
    link      selector <a>; kalau None, dicari <a href> pertama di kartu
    page_param  nama query param pagination (mis. "page"); None = satu halaman
    """
    root = base_url or "/".join(list_url.split("/")[:3])

    def _text(node, selector):
        if not selector or node is None:
            return None
        found = node.select_one(selector)
        return found.get_text(" ", strip=True) if found else None

    def fetch(query: str, limit: int) -> list[dict]:
        jobs: list[dict] = []
        seen: set[str] = set()
        page = page_start

        while len(jobs) < limit and page < page_start + max_pages:
            params = dict(extra_params or {})
            if page_param:
                params[page_param] = page
            try:
                soup = get_soup(list_url, params=params or None)
            except Exception:  # noqa: BLE001
                break

            cards = soup.select(card)
            if not cards:
                break

            before = len(jobs)
            for node in cards:
                a = node.select_one(link) if link else node.find("a", href=True)
                if not a or not a.get("href"):
                    continue
                url = urljoin(root, a["href"])
                if url in seen:
                    continue

                job_title = _text(node, title) or a.get_text(" ", strip=True)
                if not job_title:
                    continue
                job_loc = _text(node, location)
                job_fn = _text(node, function)
                if not matches(query, job_title, job_fn):
                    continue

                seen.add(url)
                jobs.append({
                    "title": job_title,
                    "url": url,
                    "job_id": url,
                    "location": job_loc,
                    "job_function": job_fn,
                    "job_level": _text(node, level),
                })
                if len(jobs) >= limit:
                    break

            if not page_param or len(jobs) == before:
                break
            page += 1

        return jobs[:limit]

    return fetch


# Label bagian yang sering tertukar dengan judul lowongan.
_LABEL_PATTERN = re.compile(
    r"^\s*(job\s*(descriptions?|qualifications?|requirements?|responsibilit\w*|"
    r"type|level|location)|deskripsi|kualifikasi|persyaratan|tanggung\s*jawab|"
    r"requirements?|qualifications?|responsibilities|about\s+the\s+role|"
    r"apply\s*now|lihat\s*detail|selengkapnya|read\s*more|view\s+similar\s+job)\b",
    re.I,
)


def _looks_like_sentence(text: str) -> bool:
    """True kalau teks ini kalimat deskripsi, bukan judul lowongan.

    Judul lowongan pendek dan tanpa tanda baca kalimat ("Sales - Southgate 2").
    Deskripsi panjang dan berpola kalimat ("Responsible for selling a unit...").
    """
    stripped = text.strip()
    if stripped.endswith("."):
        return True
    # judul jarang lebih dari 10 kata
    return len(stripped.split()) > 10


def _is_label(text: str) -> bool:
    """True kalau teks ini label bagian, bukan judul lowongan."""
    stripped = text.strip()
    if not stripped:
        return True
    if _LABEL_PATTERN.match(stripped):
        return True
    # teks pendek yang diakhiri titik dua hampir selalu label
    return stripped.endswith(":") and len(stripped) < 60


def _title_from_detail_page(url: str, selector: str | None = None) -> str | None:
    """Ambil judul lowongan dari halaman detailnya.

    Dipakai kalau halaman listing tidak memuat judul sama sekali di blok
    lowongannya. Satu request per lowongan, jadi hanya untuk situs dengan
    sedikit lowongan.
    """
    try:
        soup = get_soup(url, retries=1, timeout=20)
    except Exception:  # noqa: BLE001
        return None

    if selector:
        node = soup.select_one(selector)
        if node:
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            if text and not _is_label(text):
                return text[:150]

    for chrome in soup.find_all(["nav", "header", "footer", "script", "style"]):
        chrome.decompose()

    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
        if (text and 3 < len(text) < 120 and not _is_label(text)
                and not _looks_like_sentence(text)):
            return text

    # terakhir: <title> halaman, buang nama situs di belakang pemisah
    node = soup.find("title")
    if node:
        text = re.sub(r"\s+", " ", node.get_text(strip=True))
        text = re.split(r"\s*[|\-–—]\s*", text)[0].strip()
        if text and 3 < len(text) < 120:
            return text
    return None


# --------------------------------------------------------------------------- #
# 2b. Berbasis pola URL (tanpa perlu tahu class CSS)
# --------------------------------------------------------------------------- #
def link_pattern_fetcher(
    list_url: str,
    href_contains: str,
    title_selector: str | None = None,
    max_climb: int = 5,
    base_url: str | None = None,
    location_regex: str | None = None,
    title_from_detail: bool = False,
    detail_title_selector: str | None = None,
    title_list_selector: str | None = None,
):
    """Kenali lowongan dari POLA URL-nya, bukan dari class CSS.

    Banyak situs karir lama (ASP/PHP) tidak punya class yang stabil, tapi link
    lowongannya selalu mengandung parameter khas seperti `jid=` atau `id=`.
    Adapter ini mencari anchor yang cocok, lalu memanjat ke atas sampai ketemu
    pembungkus yang masuk akal untuk mengambil judul dan deskripsi.

    Lebih tahan banting daripada selector CSS: kalau situsnya ganti tema, pola
    URL biasanya tetap.

    location_regex: pola dengan satu grup untuk menarik lokasi dari teks,
    mis. r"[Ww]illing to be placed in ([^.]+)"
    """
    root = base_url or "/".join(list_url.split("/")[:3])

    def fetch(query: str, limit: int) -> list[dict]:
        try:
            soup = get_soup(list_url)
        except Exception:  # noqa: BLE001
            return []

        for chrome in soup.find_all(["nav", "header", "footer"]):
            chrome.decompose()

        title_list: list[str] = []
        if title_list_selector:
            for node in soup.select(title_list_selector):
                text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
                if text and len(text) < 120 and not _is_label(text):
                    title_list.append(text)

        jobs: list[dict] = []
        seen: set[str] = set()

        for index, a in enumerate(soup.select(f'a[href*="{href_contains}"]')):
            href = a.get("href") or ""
            url = urljoin(root, href)
            if url in seen:
                continue

            # Naik sampai ketemu pembungkus yang memuat cukup teks untuk
            # menampung judul + deskripsi, tapi belum sebesar seluruh halaman.
            container = a
            for _ in range(max_climb):
                if container.parent is None:
                    break
                container = container.parent
                text = container.get_text(" ", strip=True)
                if 60 < len(text) < 6000:
                    break

            title = None
            if title_list and index < len(title_list):
                title = title_list[index]
            if not title and title_selector:
                node = container.select_one(title_selector)
                title = node.get_text(" ", strip=True) if node else None
            if not title:
                for tag in container.find_all(
                        ["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"]):
                    candidate = tag.get_text(" ", strip=True)
                    if candidate and len(candidate) < 120 and not _is_label(candidate):
                        title = candidate
                        break
            if not title:
                # Judul kadang berada di luar pembungkus, sebagai heading tepat
                # sebelum blok. Tapi pencarian ini HARUS dibatasi pada saudara
                # sebelumnya — find_previous() menelusuri seluruh dokumen dan
                # pernah menarik tombol "View All Opportunities" dari bagian
                # lain halaman.
                sibling = container.find_previous_sibling()
                hops = 0
                while sibling is not None and hops < 3:
                    candidate = re.sub(
                        r"\s+", " ", sibling.get_text(" ", strip=True))
                    if (candidate and len(candidate) < 120
                            and not _is_label(candidate)
                            and not _looks_like_sentence(candidate)):
                        title = candidate
                        break
                    sibling = sibling.find_previous_sibling()
                    hops += 1
            if not title:
                # Judul sering ditulis sebagai teks biasa sementara yang ditebalkan
                # justru labelnya ("Job Descriptions:"). Jadi kalau tidak ada
                # heading yang layak, ambil baris teks pertama yang bukan label.
                for line in container.get_text("\n", strip=True).split("\n"):
                    line = line.strip()
                    if (line and len(line) < 120 and not _is_label(line)
                            and not _looks_like_sentence(line)):
                        title = line
                        break
            # Pengambilan dari halaman detail harus dilakukan SEBELUM lowongan
            # dibuang karena tak berjudul — kalau tidak, justru lowongan yang
            # paling butuh bantuan yang hilang duluan.
            if title_from_detail and not title:
                title = _title_from_detail_page(url, detail_title_selector)

            if not title:
                continue

            body = re.sub(r"\s+", " ",
                          container.get_text(" ", strip=True))[:4000]

            if not matches(query, title, body):
                continue

            location = None
            if location_regex:
                m = re.search(location_regex, body)
                if m:
                    location = m.group(1).strip().rstrip(".")

            seen.add(url)
            jobs.append({
                "title": title,
                "url": url,
                "job_id": url,
                "location": location,
                "description": body,
            })
            if len(jobs) >= limit:
                break

        return jobs

    return fetch


# --------------------------------------------------------------------------- #
# 2c. Daftar berbasis heading (satu halaman, tanpa link per lowongan)
# --------------------------------------------------------------------------- #
def heading_list_fetcher(
    list_url: str,
    heading: str,
    stop_at: str | None = None,
    location_regex: str | None = None,
    title_filter: str | None = None,
):
    """Untuk halaman yang memuat semua lowongan sebagai heading + isi di bawahnya.

    Pola khas situs WordPress: tidak ada halaman detail per lowongan, jadi
    tiap heading DIALAH lowongannya, dan isinya adalah semua elemen sampai
    heading berikutnya.

    Karena tidak ada URL unik per lowongan, `job_id` dibentuk dari judul.
    Konsekuensinya: kalau judulnya diubah pihak perusahaan, row lama tidak
    ter-update melainkan muncul sebagai lowongan baru. Itu trade-off yang
    tidak terhindarkan tanpa ID dari situsnya.

    title_filter: regex yang HARUS cocok agar heading dianggap lowongan,
    misalnya pola kurung siku untuk situs yang menandai posisi dengan
    "[Fulltime] ..." atau "[Internship] ...".
    """
    import hashlib

    def fetch(query: str, limit: int) -> list[dict]:
        try:
            soup = get_soup(list_url)
        except Exception:  # noqa: BLE001
            return []

        for chrome in soup.find_all(["nav", "header", "footer"]):
            chrome.decompose()

        pattern = re.compile(title_filter) if title_filter else None
        jobs: list[dict] = []

        for node in soup.select(heading):
            title = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            if not title or len(title) > 150:
                continue
            if pattern and not pattern.search(title):
                continue

            # kumpulkan isi sampai heading berikutnya
            parts = []
            for sibling in node.find_next_siblings():
                if stop_at and sibling.name and sibling in soup.select(stop_at):
                    break
                if sibling.name == node.name:
                    break
                text = sibling.get_text(" ", strip=True)
                if text:
                    parts.append(text)
                if sum(len(p) for p in parts) > 4000:
                    break

            body = re.sub(r"\s+", " ", " ".join(parts))[:4000] or None
            if not matches(query, title, body):
                continue

            location = None
            if location_regex and body:
                m = re.search(location_regex, body)
                if m:
                    location = m.group(1).strip().rstrip(".")

            # heading kadang punya id -> bisa jadi anchor ke posisi di halaman
            anchor = node.get("id")
            url = f"{list_url}#{anchor}" if anchor else list_url

            jobs.append({
                "title": title,
                "url": url,
                "job_id": hashlib.md5(title.encode()).hexdigest()[:16],
                "location": location,
                "description": body,
            })
            if len(jobs) >= limit:
                break

        return jobs

    return fetch


# --------------------------------------------------------------------------- #
# 2d. Blok berlabel (judul + "Label: nilai", tanpa link detail)
# --------------------------------------------------------------------------- #
def labeled_block_fetcher(
    list_url: str,
    marker: str,
    labels: dict[str, str] | None = None,
    title_tags: tuple[str, ...] = ("strong", "b", "h1", "h2", "h3", "h4", "h5"),
    max_climb: int = 6,
    id_regex: str | None = None,
):
    """Untuk listing yang menampilkan tiap lowongan sebagai blok berlabel.

    Contoh bentuk yang ditangani (Pertamina PTC):

        Sr Planner - Bengkalis, Riau [PTC0126D01765]
        Jenis Pekerjaan   Contract
        Kualifikasi       - Warga Negara Indonesia ...
        Lokasi            Riau, Indonesia

    Tidak ada link per lowongan, dan class CSS-nya tidak diketahui. Jadi blok
    dikenali dari `marker` — teks label yang PASTI muncul di tiap lowongan
    ("Jenis Pekerjaan"). Dari elemen yang memuat marker itu, naik ke atas
    sampai ketemu pembungkus yang berisi judul juga.

    labels: peta {nama_kolom: label_di_halaman}, mis.
        {"job_type": "Jenis Pekerjaan", "location": "Lokasi"}
    id_regex: pola regex untuk menarik kode lowongan dari judul, misalnya
        kode dalam kurung siku seperti "[PTC0126D01765]".
    """
    import hashlib

    labels = labels or {}

    def fetch(query: str, limit: int) -> list[dict]:
        try:
            soup = get_soup(list_url)
        except Exception:  # noqa: BLE001
            return []

        for chrome in soup.find_all(["nav", "header", "footer", "script", "style"]):
            chrome.decompose()

        # semua label di halaman, untuk tahu di mana satu nilai harus berhenti
        all_labels = [re.escape(v) for v in labels.values()]
        stop = (r"(?=\s*(?:" + "|".join(all_labels) + r"|$))") if all_labels else "$"

        jobs: list[dict] = []
        seen: set[str] = set()

        nilai_label = set(labels.values())

        def _layak(teks: str) -> bool:
            return bool(
                teks and len(teks) < 160
                and marker not in teks
                and not _is_label(teks)
                and teks not in nilai_label
            )

        pola_marker = re.compile(re.escape(marker))

        for node in soup.find_all(string=pola_marker):
            # Tentukan batas blok lowongan ini: leluhur TERBESAR yang masih
            # memuat marker HANYA SATU KALI. Begitu naik satu tingkat lagi
            # membuat marker muncul dua kali, berarti kita sudah menyentuh
            # lowongan berikutnya dan harus berhenti.
            #
            # Tanpa batas ini, pemanjatan menembus sampai pembungkus seluruh
            # daftar — semua lowongan jadi satu blok, hanya satu yang terbaca,
            # dan nilai labelnya melahap isi lowongan setelahnya.
            container = node.parent
            for _ in range(max_climb):
                induk = container.parent if container is not None else None
                if induk is None:
                    break
                if len(induk.find_all(string=pola_marker)) > 1:
                    break
                container = induk

            title = None

            # 1) Cari judul DI DALAM blok.
            if container is not None:
                for tag in container.find_all(title_tags):
                    candidate = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
                    if _layak(candidate):
                        title = candidate
                        break

            # 2) Kalau tidak ketemu, judulnya berada DI LUAR blok label.
            #
            # Pertamina PTC begini: <b>Sr Planner – Bengkalis [PTC0126D01765]</b>
            # berdiri sendiri, lalu blok berisi "Jenis Pekerjaan", "Kualifikasi",
            # dan "Lokasi" menyusul sebagai elemen terpisah. Naik lima tingkat
            # dari marker pun tidak pernah menjangkau judulnya.
            #
            # Jadi telusuri mundur dalam urutan dokumen sampai ketemu heading
            # yang bukan label. Dibatasi beberapa lompatan supaya tidak
            # menyeret judul milik lowongan sebelumnya.
            if not title and container is not None:
                sebelumnya = container
                for _ in range(6):
                    sebelumnya = sebelumnya.find_previous(title_tags)
                    if sebelumnya is None:
                        break
                    candidate = re.sub(
                        r"\s+", " ", sebelumnya.get_text(" ", strip=True))
                    if _layak(candidate):
                        title = candidate
                        break

            if not title or title in seen:
                continue
            seen.add(title)

            body = re.sub(r"\s+", " ",
                          container.get_text(" ", strip=True))[:6000]
            if not matches(query, title, body):
                continue

            job = {"title": title, "url": list_url, "description": body}

            for column, label in labels.items():
                pattern = re.escape(label) + r"\s*[:\-]?\s*(.{2,400}?)" + stop
                m = re.search(pattern, body)
                if m:
                    value = m.group(1).strip(" :-–—").strip()
                    if value:
                        job[column] = value[:400] if column == "description" else value[:120]

            code = None
            if id_regex:
                m = re.search(id_regex, title)
                if m:
                    code = m.group(1).strip()
            job["job_id"] = code or hashlib.md5(title.encode()).hexdigest()[:16]

            jobs.append(job)
            if len(jobs) >= limit:
                break

        return jobs

    return fetch


# --------------------------------------------------------------------------- #
# 3. Playwright untuk SPA
# --------------------------------------------------------------------------- #
def playwright_fetcher(
    list_url: str,
    card: str,
    title: str | None = None,
    link: str | None = None,
    location: str | None = None,
    wait_for: str | None = None,
    wait_ms: int = 4000,
    scroll_rounds: int = 6,
    base_url: str | None = None,
    timeout_ms: int = 45000,
):
    """Render halaman pakai Chromium headless, lalu ambil kartu loker.

    Dipakai hanya kalau situsnya benar-benar SPA. Berat (~3-8 detik/situs),
    jadi situs bertipe ini ditandai needs_browser=True dan bisa di-skip lewat
    alias `fast`.
    """
    root = base_url or "/".join(list_url.split("/")[:3])

    def fetch(query: str, limit: int) -> list[dict]:
        from playwright.sync_api import sync_playwright

        jobs: list[dict] = []
        seen: set[str] = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            try:
                page.goto(list_url, timeout=timeout_ms, wait_until="domcontentloaded")
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=timeout_ms)
                    except Exception:  # noqa: BLE001
                        pass
                page.wait_for_timeout(wait_ms)

                # infinite scroll / lazy load
                for _ in range(scroll_rounds):
                    if page.locator(card).count() >= limit:
                        break
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(1200)

                nodes = page.locator(card)
                for i in range(min(nodes.count(), limit * 3)):
                    node = nodes.nth(i)
                    try:
                        href = (
                            node.locator(link).first.get_attribute("href")
                            if link else node.get_attribute("href")
                            or node.locator("a").first.get_attribute("href")
                        )
                        if not href:
                            continue
                        url = urljoin(root, href)
                        if url in seen:
                            continue
                        job_title = (
                            node.locator(title).first.inner_text()
                            if title else node.inner_text()
                        ).strip().split("\n")[0]
                        if not job_title or not matches(query, job_title):
                            continue
                        job_loc = None
                        if location and node.locator(location).count():
                            job_loc = node.locator(location).first.inner_text().strip()
                        seen.add(url)
                        jobs.append({
                            "title": job_title, "url": url, "job_id": url,
                            "location": job_loc,
                        })
                        if len(jobs) >= limit:
                            break
                    except Exception:  # noqa: BLE001
                        continue
            finally:
                browser.close()

        return jobs

    return fetch


# --------------------------------------------------------------------------- #
# Helper registrasi
# --------------------------------------------------------------------------- #
def register_html(
    kind: str, name: str, label: str, company: str,
    industry: str | None = None, company_url_direct: str | None = None,
    verified: bool = False, tags: set[str] | None = None, notes: str = "",
    enrich=None,
    **cfg,
) -> SiteSpec:
    factory = {
        "successfactors": successfactors_fetcher,
        "static": static_html_fetcher,
        "link_pattern": link_pattern_fetcher,
        "heading_list": heading_list_fetcher,
        "labeled_block": labeled_block_fetcher,
        "playwright": playwright_fetcher,
    }[kind]
    return register(SiteSpec(
        name=name, label=label, company=company,
        fetch=factory(**cfg),
        industry=industry,
        company_url=cfg.get("list_url") or cfg.get("base_url"),
        company_url_direct=company_url_direct,
        needs_browser=(kind == "playwright"),
        verified=verified,
        enrich=enrich,
        tags=(tags or set()) | {kind},
        notes=notes,
    ))
