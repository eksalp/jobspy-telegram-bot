from __future__ import annotations

"""
Scraper untuk career.astra.co.id.

PENTING: situs ini adalah single-page app (React/Vue) - konten loker di-load lewat
JavaScript setelah halaman jalan, jadi TIDAK bisa di-scrape pakai requests biasa.
Modul ini pakai Playwright (browser virtual/headless) untuk render halaman dulu,
baru ambil datanya.

CATATAN JUJUR: selector CSS di bawah ini disusun berdasarkan pola umum web app
listing loker, TAPI belum divalidasi langsung terhadap struktur asli
career.astra.co.id (keterbatasan lingkungan saat kode ini ditulis). Kemungkinan
besar perlu disesuaikan setelah kamu coba jalankan & lihat errornya / hasilnya
kosong. Kalau itu terjadi, kabari sambil share info error-nya biar bisa dibantu
perbaiki selector-nya.
"""

from playwright.sync_api import sync_playwright

from categorize import classify_job, classify_work_arrangement, classify_employment_type

BASE_URL = "https://career.astra.co.id"
SEARCH_URL = f"{BASE_URL}/lowongan"


ALL_KEYWORDS = {"all", "semua", "*"}


def search_astra_career(query: str, limit: int = 20, timeout_ms: int = 45000) -> list[dict]:
    """Cari loker di career.astra.co.id pakai browser virtual (Playwright).
    Kalau `query` adalah "all"/"semua"/"*", search box dilewati - langsung ambil
    semua loker yang tampil di halaman listing (dengan coba klik pagination kalau
    ada, best-effort, sampai limit tercapai).
    Return list of dict: {title, url, company, location}
    """
    results: list[dict] = []
    browse_all = query.strip().lower() in ALL_KEYWORDS

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            for attempt in range(3):
                try:
                    page.goto(SEARCH_URL, timeout=timeout_ms, wait_until="load")
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    page.wait_for_timeout(3000)  # jeda sebentar sebelum coba lagi
            page.wait_for_timeout(3000)  # kasih waktu tambahan buat JS render konten

            if not browse_all:
                search_input_selectors = [
                    'input[type="search"]',
                    'input[placeholder*="cari" i]',
                    'input[placeholder*="posisi" i]',
                    'input[type="text"]',
                    "input",
                ]
                filled = False
                for sel in search_input_selectors:
                    try:
                        loc = page.locator(sel)
                        if loc.count() > 0:
                            loc.first.click()
                            loc.first.fill(query)
                            filled = True
                            break
                    except Exception:
                        continue

                if filled:
                    try:
                        cari_btn = page.get_by_text("Cari", exact=True)
                        if cari_btn.count() > 0:
                            cari_btn.first.click()
                        else:
                            page.keyboard.press("Enter")
                    except Exception:
                        page.keyboard.press("Enter")

                page.wait_for_timeout(3000)

            def scrape_current_page() -> list[dict]:
                return page.evaluate(
                    """
                    () => {
                        const anchors = Array.from(document.querySelectorAll('a'))
                            .filter(a => a.textContent.trim() === 'Lihat Detail');
                        const out = [];
                        for (const a of anchors) {
                            let container = a;
                            let found = null;
                            for (let i = 0; i < 8 && container; i++) {
                                container = container.parentElement;
                                if (!container) break;
                                const heading = container.querySelector('h1,h2,h3,h4,h5,strong');
                                if (heading && heading.textContent.trim().length > 3) {
                                    const links = Array.from(container.querySelectorAll('a'));
                                    const companyLink = links.find(
                                        l => l !== a && l.textContent.trim().length > 1
                                        && l.textContent.trim() !== 'Lamar'
                                        && l.textContent.trim() !== 'Lihat Detail'
                                    );
                                    found = {
                                        title: heading.textContent.trim(),
                                        company: companyLink ? companyLink.textContent.trim() : null,
                                        url: a.href,
                                    };
                                    break;
                                }
                            }
                            if (found) out.push(found);
                        }
                        return out;
                    }
                    """
                )

            seen_urls: set[str] = set()
            max_pages = 15 if browse_all else 1
            current_page = 1

            for _ in range(max_pages):
                page_jobs = scrape_current_page()
                new_count = 0
                for job in page_jobs:
                    url = job.get("url")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    new_count += 1
                    results.append(
                        {
                            "title": job.get("title"),
                            "url": url,
                            "company": job.get("company"),
                            "location": None,
                        }
                    )
                    if len(results) >= limit:
                        break

                if len(results) >= limit or not browse_all:
                    break

                # klik nomor halaman berikutnya (1, 2, 3, ...) - situs ini pakai
                # pagination angka, bukan tombol "Next" teks. Pakai JS langsung
                # buat cari elemen paling "dalam" (leaf, gak ada child) yang
                # teksnya PERSIS sama dengan nomor halaman - lebih tahan banting
                # terhadap struktur HTML yang gak terduga dibanding locator biasa.
                next_page_num = current_page + 1
                next_clicked = False
                for pagination_attempt in range(2):
                    try:
                        clicked = page.evaluate(
                            """
                            (target) => {
                                const all = Array.from(document.querySelectorAll('a, button, span, li, div'));
                                let candidates = all.filter(
                                    el => el.textContent.trim() === target && el.children.length === 0
                                );
                                if (candidates.length === 0) {
                                    candidates = all.filter(el => el.textContent.trim() === target);
                                }
                                if (candidates.length === 0) return false;
                                candidates[0].scrollIntoView({block: 'center'});
                                candidates[0].click();
                                return true;
                            }
                            """,
                            str(next_page_num),
                        )
                    except Exception:
                        clicked = False

                    if clicked:
                        page.wait_for_timeout(3000)
                        current_page = next_page_num
                        next_clicked = True
                        break

                    page.wait_for_timeout(2000)  # kasih waktu ekstra, pagination mungkin belum ke-render

                if not next_clicked or new_count == 0:
                    break  # nggak ada halaman berikutnya / nggak ada hasil baru

        finally:
            browser.close()

    return results[:limit]


def astra_career_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str,
    requested_by_chat_id: str,
) -> list[dict]:
    records = []
    for job in jobs:
        url = job.get("url")
        if not url:
            continue
        record = {
            "job_id": url,
            "site": "astracareer",
            "job_url": url,
            "job_url_direct": url,
            "title": job.get("title"),
            "company": job.get("company") or "Astra Group",
            "location": job.get("location") or search_location,
            "date_posted": None,
            "job_type": None,
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": None,
            "job_level": None,
            "job_function": None,
            "listing_type": None,
            "emails": None,
            "description": None,
            "company_industry": None,
            "company_url": None,
            "company_logo": None,
            "company_url_direct": None,
            "company_addresses": None,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": None,
            "experience_range": None,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": None,
            "raw_salary": None,
            "category": classify_job(job.get("title"), search_term),
            "work_arrangement": classify_work_arrangement(
                None, job.get("title"), job.get("location")
            ),
            "employment_type": classify_employment_type(None, job.get("title")),
            "search_term": search_term,
            "search_location": search_location,
            "requested_by_chat_id": str(requested_by_chat_id),
        }
        records.append(record)
    return records
