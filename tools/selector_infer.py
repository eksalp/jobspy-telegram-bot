from __future__ import annotations

"""
Menebak CSS selector kartu loker dengan menganalisis struktur DOM yang berulang.

Ide dasarnya: di halaman listing loker, tiap lowongan hampir selalu dibungkus
elemen dengan tag+class yang sama persis, diulang N kali sebagai bersaudara.
Jadi:

  1. Kumpulkan semua <a> yang href-nya mirip link lowongan
  2. Dari tiap <a>, telusuri ke atas cari leluhur yang punya >=3 saudara
     dengan tanda tangan (tag + class) identik  -> itu kartu lokernya
  3. Di dalam kartu, cari elemen judul (heading, atau anchor-nya sendiri)
  4. Cari elemen yang teksnya mengandung nama kota Indonesia -> lokasi

Hasilnya tebakan, bukan kepastian. Tapi biasanya cukup dekat untuk langsung
dipakai, atau minimal jadi titik awal yang jauh lebih baik daripada nol.
"""

import re
from collections import Counter

JOB_HREF = re.compile(
    r"(job|career|karir|karier|lowongan|vacanc|position|opening|detail)",
    re.I,
)

# kata yang menandakan link navigasi, bukan lowongan
NAV_WORDS = re.compile(
    r"(login|masuk|daftar|register|faq|tentang|about|contact|kontak|privacy|"
    r"kebijakan|syarat|term|home|beranda|facebook|instagram|twitter|linkedin|"
    r"youtube|whatsapp|tiktok)",
    re.I,
)

CITIES = re.compile(
    r"(jakarta|bandung|surabaya|medan|semarang|yogya|jogja|bekasi|tangerang|"
    r"depok|bogor|makassar|palembang|batam|denpasar|bali|malang|solo|cikarang|"
    r"karawang|balikpapan|pekanbaru|indonesia|remote|pusat|selatan|utara|"
    r"barat|timur)",
    re.I,
)

LEVEL_WORDS = re.compile(
    r"(fresh\s*grad|entry|junior|senior|manager|supervisor|staff|intern|"
    r"magang|experienced|lead|head|officer|associate)",
    re.I,
)


CHROME_CLASS = re.compile(
    r"(^|[-_])(nav|navbar|menu|footer|header|topbar|sidebar|breadcrumb|"
    r"banner|hero|social|dropdown)([-_]|$)",
    re.I,
)


def _signature(tag) -> str | None:
    """Tanda tangan elemen: nama tag + class-nya, sebagai CSS selector."""
    if not getattr(tag, "name", None):
        return None
    classes = tag.get("class") or []
    # buang class yang jelas dinamis (hash CSS-in-JS, angka, state)
    stable = [
        c for c in classes
        if not re.fullmatch(r"[a-z]{2,8}[-_]?[0-9a-f]{5,}", c, re.I)
        and not re.fullmatch(r"(active|selected|open|show|hidden|is-\w+)", c, re.I)
        and len(c) > 1
    ]
    if not stable:
        return None
    # tolak elemen kerangka halaman
    if any(CHROME_CLASS.search(c) for c in stable):
        return None
    # `div.container` dan sejenisnya terlalu generik untuk jadi kartu loker
    if len(stable) == 1 and re.fullmatch(
            r"(container|container-fluid|row|col|wrapper|content|main|section|"
            r"inner|body|page|block)([-_]\w+)?", stable[0], re.I):
        return None
    return tag.name + "".join(f".{c}" for c in stable[:3])


def _text_of(tag) -> str:
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True))[:200]


def infer_selectors(html: str, max_samples: int = 3) -> dict:
    """Return {'card','title','location','level','confidence','samples','count'}."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # --- 1. anchor kandidat lowongan ---
    # Buang dulu kerangka halaman. Menu navigasi juga struktur berulang, dan
    # tanpa ini justru dialah yang paling sering menang — itu sebabnya scan
    # pertama banyak menghasilkan li.menu-item dan ul.nav.
    for chrome in soup.find_all(["nav", "header", "footer", "aside"]):
        chrome.decompose()

    anchors = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = _text_of(a)
        if not JOB_HREF.search(href):
            continue
        # anchor yang masih berada di dalam pembungkus bernama nav/menu/footer
        if any(CHROME_CLASS.search(" ".join(p.get("class") or []))
               for p in a.parents if getattr(p, "get", None)):
            continue
        if NAV_WORDS.search(href) and not JOB_HREF.search(href.split("?")[0].split("/")[-1]):
            continue
        if NAV_WORDS.fullmatch(text.strip()):
            continue
        anchors.append(a)

    if len(anchors) < 2:
        return {"card": None, "confidence": "tidak cukup data",
                "count": len(anchors), "samples": []}

    # --- 2. cari level leluhur yang berulang ---
    # untuk tiap anchor, naik maksimal 6 tingkat, catat tanda tangan tiap tingkat
    sig_counter: Counter = Counter()
    sig_nodes: dict[str, list] = {}

    for a in anchors:
        node = a
        for _ in range(6):
            node = node.parent
            if node is None or node.name in {"body", "html", "[document]"}:
                break
            sig = _signature(node)
            if not sig:
                continue
            sig_counter[sig] += 1
            sig_nodes.setdefault(sig, []).append(node)

    if not sig_counter:
        # fallback: pakai anchor-nya langsung sebagai kartu
        sig = _signature(anchors[0]) or "a"
        return {
            "card": sig, "title": None, "location": None, "level": None,
            "confidence": "rendah (tidak ada pembungkus berulang, pakai anchor)",
            "count": len(anchors),
            "samples": [_text_of(a) for a in anchors[:max_samples]],
        }

    # kartu terbaik: yang muncul paling sering, tapi bukan container global
    # (container global membungkus SEMUA anchor, jadi jumlah node uniknya 1)
    best_sig, best_score = None, -1
    for sig, count in sig_counter.most_common(15):
        unique_nodes = {id(n) for n in sig_nodes[sig]}
        if len(unique_nodes) < 2:
            continue  # ini wrapper tunggal, bukan kartu berulang
        # skor: makin banyak node unik makin bagus, tapi harus <= jumlah anchor
        score = len(unique_nodes)
        if score > best_score:
            best_sig, best_score = sig, score

    if not best_sig:
        best_sig = sig_counter.most_common(1)[0][0]
        best_score = 1

    cards = []
    seen_ids = set()
    for node in sig_nodes[best_sig]:
        if id(node) not in seen_ids:
            seen_ids.add(id(node))
            cards.append(node)

    # --- 3. judul di dalam kartu ---
    title_sel = None
    sample = cards[0] if cards else None
    if sample:
        for cand in sample.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b"]):
            if _text_of(cand):
                title_sel = _signature(cand) or cand.name
                break
        if not title_sel:
            inner_a = sample.find("a", href=True)
            if inner_a:
                title_sel = _signature(inner_a) or "a"

    # --- 4. lokasi & level ---
    location_sel = level_sel = None
    if sample:
        for cand in sample.find_all(True):
            text = _text_of(cand)
            if not text or len(text) > 60:
                continue
            if location_sel is None and CITIES.search(text):
                location_sel = _signature(cand) or cand.name
            # jangan pilih elemen judul sebagai level — kata seperti "Staff"
            # atau "Manager" wajar muncul di judul lowongan
            cand_sig = _signature(cand) or cand.name
            if (level_sel is None and cand_sig != title_sel
                    and LEVEL_WORDS.search(text)):
                level_sel = cand_sig

    confidence = (
        "tinggi" if best_score >= 5
        else "sedang" if best_score >= 3
        else "rendah"
    )

    return {
        "card": best_sig,
        "title": title_sel,
        "location": location_sel,
        "level": level_sel,
        "confidence": f"{confidence} ({best_score} kartu terdeteksi)",
        "count": best_score,
        "samples": [_text_of(c) for c in cards[:max_samples]],
    }
