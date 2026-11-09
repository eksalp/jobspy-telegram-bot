from __future__ import annotations

"""
Klasifikasi otomatis kategori/bidang loker, lokasi kerja, dan tipe pekerjaan.
Berbasis keyword matching sederhana — cepat, gratis, tidak butuh API eksternal.

Nilai yang dihasilkan (Bahasa Indonesia, konsisten dengan filter di frontend):
  work_arrangement : onsite | remote | hybrid
  employment_type  : full-time | kontrak | freelance | magang | part-time
"""

import re

# ─── KATEGORI BIDANG ─────────────────────────────────────────────────────────

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "software-engineering": [
        "software engineer", "software developer", "programmer",
        "engineer perangkat lunak", " swe ", "backend developer", "frontend developer",
        "system analyst", "systems analyst", "erp ", "sap consultant", "it staff",
        "it support", "helpdesk", "help desk", "robotics",
    ],
    "frontend": [
        "frontend", "front-end", "front end", "react developer", "vue developer",
        "angular developer", "ui developer",
    ],
    "backend": [
        "backend", "back-end", "back end developer", "back end engineer", "api developer", "server side",
        "node.js developer", "django developer", "laravel developer",
        "golang developer", "java developer", ".net developer", "php developer",
    ],
    "fullstack": ["fullstack", "full-stack", "full stack"],
    "mobile-development": [
        "mobile developer", "android developer", "ios developer", "flutter developer",
        "react native", "swift developer", "kotlin developer",
    ],
    "data-science": [
        "data scientist", "machine learning", "ml engineer", "ai engineer",
        "data science", "nlp engineer", "computer vision",
    ],
    "data-analyst": [
        "data analyst", "business intelligence", "bi analyst", "data engineer",
        "analis data",
    ],
    "devops-infrastructure": [
        "devops", "site reliability", " sre ", "infrastructure engineer",
        "cloud engineer", "platform engineer", "system administrator", "sysadmin",
    ],
    "cybersecurity": [
        "cyber security", "cybersecurity", "security engineer", "penetration tester",
        "infosec", "keamanan siber",
    ],
    "blockchain-web3": [
        "blockchain", "web3", "solidity", "smart contract", "crypto", "defi", "nft",
    ],
    
    "product-management": ["product manager", "product owner", "product management"],
    "project-management": [
        "project manager", "project management", "scrum master", "manajer proyek",
    ],
    "design-ui-ux": [
        "ui/ux", "ui ux", "ux designer", "ui designer", "product designer",
        "graphic designer", "desainer grafis", "desainer produk",
    ],
    "qa-testing": [
        "qa engineer", "quality assurance", "software tester", "test engineer",
        "automation tester", "penguji perangkat lunak",
    ],
    "finance-accounting": [
        "finance", "financial", "keuangan", "akuntansi", "accounting", "accountant",
        "treasury", " tax ", "pajak", "audit", "auditor", "bookkeeping",
        "credit analys", "analis kredit", "credit processing", "wealth management",
        "akuntan", "accounts receivable", "account receivable", "accounts payable",
        "account payable", "penagihan", "collection", "remedial officer",
        "bankir", "banker", "perbankan", "kasir bank", "teller",
    ],
    "marketing": [
        "marketing", "pemasaran", "digital marketing", "brand ", "seo specialist",
        "content marketing", "social media specialist", "content creator",
    ],
    "sales-business-development": [
        "sales", "business development", "account executive", "account manager",
        "tenaga penjual", "relationship manager", "relationship officer",
        "branch manager", "area manager",
        "medical representative", "staf penjualan", "staff penjualan", "penjualan",
        "key account", "sales promotion", " spg ", " spb ", "aktivasi promosi",
        "staff promotion", "canvasser", "telemarketing", "agen asuransi",
        "insurance agent", "assurance consultant", "account officer",
        "business officer", "merchant business", "funding officer",
    ],
    "human-resources": [
        "human resources", " hr ", "hrbp", "recruiter", "recruitment",
        "talent acquisition", "sumber daya manusia", "people operations",
        "hr generalist", "hr officer",
    ],
    "customer-service": [
        "customer service", "customer support", "cs officer", "call center",
        "layanan pelanggan", "customer success",
        "guest service", "layanan tamu", "front office", "call centre",
    ],
    "operations-logistics": [
        "operations", "operasional", "logistics", "logistik", "supply chain",
        "warehouse", "gudang", "procurement", "pengadaan",
        "kurir", "courier", "driver", "supir", "sopir", "hub lead", "middle mile",
        "first mile", "last mile", "sortation", "sorter", "shift lead",
        "delivery driver", "delivery staff", "pengiriman", "ekspedisi", "dispatcher",
        "operation ", "process improvement", "service point",
        "logistic", "inventory", "stock keeper", "checker",
    ],
    "legal": ["legal officer", "lawyer", "pengacara", "legal counsel", "compliance officer"],
    "engineering-non-it": [
        "mechanical engineer", "electrical engineer", "civil engineer",
        "teknik mesin", "teknik sipil", "teknik elektro", "industrial engineer",
        "teknik industri",
        "teknisi", "technician", "mekanik", "mechanic", "maintenance",
        "electrical", "listrik", "operator produksi", "production operator",
        "operator production", "produksi", "production staff", "production supervisor",
        "quality control",
        " qc ", "estimator", "drafter", "hse", " k3 ", "safety officer",
        "environment engineer", "utility",
    ],
    "healthcare": [
        "nurse", "perawat", " dokter", "doctor", "healthcare", "medical staff",
        "apoteker", "pharmacist", "bidan",
        "gizi", "kesehatan masyarakat", "farmasi", "klinik", "caregiver",
    ],
    "education": [
        "teacher", " guru ", "dosen", "trainer", "instruktur", "tutor",
        "pengajar", "pembimbing", "mengajar", "konselor pendidikan", "utbk",
        "education and training",
    ],
    "admin-general": [
        "admin ", "administrasi", "staff umum", "general affair", "ga staff",
        "data entry",
        "staff administrasi", "staf administrasi", "admistrasi", "office manager",
        "receptionist", "resepsionis", "sekretaris", "secretary",
    ],
    "food-beverage": [
        " cook", "koki", "chef", "juru masak", "kitchen", "dapur", "waiter",
        "waitress", "pramusaji", "pelayan restoran", "barista", "bartender",
        "steward", "restoran", "restaurant", "cafe ", "kafe", "f&b", "baker",
        "pastry",
    ],
    "retail-store": [
        "crew store", "store crew", "crew outlet", "staff outlet", "staf outlet",
        "crew toko", "penjaga toko", "shopkeeper", "kepala toko", "store manager",
        "kasir", "cashier", "beauty advisor", "merchandiser", "pramuniaga",
        "retail", "minimarket", "outlet",
    ],
    "hospitality-household": [
        "housekeeping", "room attendant", "cleaning", "cleaner", "kebersihan",
        "office boy", "office girl", "helper office", "asisten rumah tangga",
        "pembantu rumah tangga", "baby sitter", "babysitter", "pengasuh",
        "pendamping lansia", "perawat lansia", "security", "satpam",
        "petugas keamanan", "hotel", "serabutan", "tukang", "cuci mobil",
        "poles mobil", "car wash", "sarang burung walet",
    ],
    "beauty-wellness": [
        "terapis", "therapist", "massage", "pijat", " spa ", "beautician",
        "kapster", "hair stylist", "nail artist", "makeup artist", " mua ",
    ],
    "media-creative": [
        "videographer", "video editor", "editor video", "photographer",
        "fotografer", "animator", "3d artist", "content writer", "copywriter",
        "media and creatives", "creative", "kreatif", "event coordinator", "editor",
        "event manager", "event organizer",
    ],
    "management-trainee": [
        "management trainee", "mt program", "graduate program",
        "fresh graduate program", " odp ", "officer development program",
        "management development program", "program trainee", "trainee program",
        "development program", "ikatan dinas",
    ],
    "internship": ["intern ", " intern", "magang", "internship"],
}


def classify_job(*text_parts: str | None) -> str | None:
    combined = " ".join(p for p in text_parts if p).lower()
    combined = f" {combined} "
    combined = re.sub(r"\s+", " ", combined)
    matched = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                matched.append(category)
                break
    return ", ".join(matched) if matched else None


# ─── LOKASI KERJA ─────────────────────────────────────────────────────────────

REMOTE_KEYWORDS = [
    "remote", "wfh", "work from home", "kerja dari rumah", "fully remote",
    "remote-first", "kerja jarak jauh", "worldwide", "anywhere", "global",
    "work from anywhere",
]
HYBRID_KEYWORDS = ["hybrid", "kerja hybrid"]
ONSITE_KEYWORDS = ["on-site", "onsite", "on site", "wfo", "work from office", "in-office"]


def classify_work_arrangement(
    is_remote: bool | None, *text_parts: str | None
) -> str:
    """Lokasi kerja: onsite | remote | hybrid. Selalu ada nilai, default onsite."""
    combined = " ".join(p for p in text_parts if p).lower()
    combined = f" {combined} "
    combined = re.sub(r"\s+", " ", combined)

    if is_remote is True:
        return "remote"
    if any(kw in combined for kw in HYBRID_KEYWORDS):
        return "hybrid"
    if any(kw in combined for kw in REMOTE_KEYWORDS):
        return "remote"
    if any(kw in combined for kw in ONSITE_KEYWORDS):
        return "onsite"
    return "onsite"  # default


# ─── TIPE PEKERJAAN ───────────────────────────────────────────────────────────

MAGANG_KEYWORDS = [
    " intern ", "magang", "internship", "apprentice", "trainee",
    "apprenticeship", "fresh graduate program", "management trainee",
    "graduate program", " odp ", "officer development program",
]
FREELANCE_KEYWORDS = [
    "freelance", "freelancer", "kerja lepas", "project based", "project-based",
    "per proyek", "kontrak lepas", " gig ",
]
KONTRAK_KEYWORDS = [
    "contract", "kontrak", "pkwt", "temporary", "sementara",
]
PARTTIME_KEYWORDS = [
    "part-time", "part time", "parttime", "paruh waktu", "part_time",
]
FULLTIME_KEYWORDS = [
    "full-time", "full time", "fulltime", "waktu penuh", "permanent",
    "tetap", "karyawan tetap", "full_time",
]


def classify_employment_type(
    job_type_raw: str | None, *text_parts: str | None
) -> str:
    """Tipe pekerjaan: full-time | kontrak | freelance | magang | part-time.
    Selalu ada nilai, default full-time.
    """
    combined_parts = [job_type_raw] + list(text_parts)
    combined = " ".join(p for p in combined_parts if p).lower()
    combined = f" {combined} "
    combined = re.sub(r"\s+", " ", combined)

    if any(kw in combined for kw in MAGANG_KEYWORDS):
        return "magang"
    if any(kw in combined for kw in FREELANCE_KEYWORDS):
        return "freelance"
    if any(kw in combined for kw in KONTRAK_KEYWORDS):
        return "kontrak"
    if any(kw in combined for kw in PARTTIME_KEYWORDS):
        return "part-time"
    if any(kw in combined for kw in FULLTIME_KEYWORDS):
        return "full-time"
    return "full-time"  # default
