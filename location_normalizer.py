from __future__ import annotations

"""
Normalisasi lokasi mentah jadi (country, region) yang konsisten.

MASALAH YANG DISELESAIKAN: kolom `location` di tabel `jobs` diisi 23 adapter
berbeda, masing-masing dengan format sendiri. Jakarta Selatan saja muncul
sebagai empat bentuk berbeda di database:

    "Kota Adm. Jakarta Selatan"
    "South Jakarta, Jakarta"
    "Jakarta Selatan, Indonesia"
    "South Jakarta, DKI Jakarta, Indonesia"

Dan ada lowongan luar negeri tercampur (São Paulo, Manila, Bangkok, Singapore,
Kuala Lumpur, Ho Chi Minh City) — kemungkinan dari LinkedIn/JobSpy atau
lowongan remote global. Tanpa filter negara, itu ikut nongol di pencarian
"Jakarta".

CARA PAKAI

    from location_normalizer import normalize_location

    country, region = normalize_location("Kota Adm. Jakarta Selatan")
    # country="Indonesia", region="jabodetabek"

    country, region = normalize_location("São Paulo, Brazil")
    # country="Brazil", region=None

    country, region = normalize_location(None)
    # country=None, region=None

REGION HANYA BERLAKU UNTUK INDONESIA. Negara lain selalu region=None — Jobly
memakai kolom `country` saja untuk memfilter/menampilkan lowongan luar negeri,
tidak perlu breakdown region untuk itu.

REGION YANG DIPAKAI (8 pilihan + None untuk yang tak dikenali):
    jabodetabek        DKI Jakarta, Bogor, Depok, Tangerang, Bekasi
    jawa               Jawa Barat/Tengah/Timur, DIY, Banten — MINUS Jabodetabek
    sumatera           Semua provinsi di Sumatera
    kalimantan         Semua provinsi di Kalimantan
    sulawesi           Semua provinsi di Sulawesi
    bali_nusra         Bali, NTB, NTT
    indonesia_timur    Maluku, Maluku Utara, Papua dan pemekarannya
    remote             Status kerja (WFH/remote), bukan wilayah geografis

CATATAN PENTING soal Jabodetabek: didahulukan sebelum pengecekan provinsi.
Bogor/Depok/Tangerang/Bekasi secara administratif masuk Jawa Barat/Banten,
tapi di sini SENGAJA dipisah jadi region sendiri karena itu yang diminta —
kalau tidak, kota-kota itu akan tertangkap oleh aturan provinsi "Jawa" duluan.

Karawang dan Purwakarta (wilayah industri penyangga Jakarta) DIMASUKKAN ke
"jawa", BUKAN "jabodetabek", mengikuti definisi resmi BPS. Kalau ternyata mau
digeser ke Jabodetabek, cukup pindahkan entrinya di _KOTA_KE_PROVINSI /
_JABODETABEK_KHUSUS di bawah.

KELENGKAPAN KAMUS: dibangun dari data location yang BENAR-BENAR ada di
database (query GROUP BY location), ditambah kota/kabupaten besar lain per
provinsi supaya tidak cuma menutup yang sudah pernah muncul. Kalau ada lokasi
baru yang tidak dikenali kamus ini, `normalize_location` mengembalikan
(None, None) alih-alih menebak — lebih baik "tidak diketahui" yang jujur
daripada silap memetakan ke region yang salah. Jalankan
`laporkan_tidak_dikenali()` (lihat backfill_location.py) untuk melihat mana
saja yang perlu ditambahkan.
"""

import re

# --------------------------------------------------------------------------- #
# 1. Terjemahan istilah Inggris -> Indonesia
# --------------------------------------------------------------------------- #
# Beberapa sumber (JobStreet, LinkedIn/JobSpy) menulis nama wilayah Jakarta dan
# provinsi dalam bahasa Inggris. Diterjemahkan dulu sebelum dicocokkan ke
# kamus kota/kabupaten, supaya satu kamus saja cukup untuk kedua bahasa.
_TERJEMAHAN_ARAH = [
    (re.compile(r"\bSouth Jakarta\b", re.I), "Jakarta Selatan"),
    (re.compile(r"\bNorth Jakarta\b", re.I), "Jakarta Utara"),
    (re.compile(r"\bWest Jakarta\b", re.I), "Jakarta Barat"),
    (re.compile(r"\bEast Jakarta\b", re.I), "Jakarta Timur"),
    (re.compile(r"\bCentral Jakarta\b", re.I), "Jakarta Pusat"),
    (re.compile(r"\bEast Java\b", re.I), "Jawa Timur"),
    (re.compile(r"\bWest Java\b", re.I), "Jawa Barat"),
    (re.compile(r"\bCentral Java\b", re.I), "Jawa Tengah"),
    (re.compile(r"\bSouth Sumatra\b", re.I), "Sumatera Selatan"),
    (re.compile(r"\bNorth Sumatra\b", re.I), "Sumatera Utara"),
    (re.compile(r"\bWest Sumatra\b", re.I), "Sumatera Barat"),
    (re.compile(r"\bSouth Sulawesi\b", re.I), "Sulawesi Selatan"),
    (re.compile(r"\bNorth Sulawesi\b", re.I), "Sulawesi Utara"),
    (re.compile(r"\bSouth Kalimantan\b", re.I), "Kalimantan Selatan"),
    (re.compile(r"\bEast Kalimantan\b", re.I), "Kalimantan Timur"),
    (re.compile(r"\bWest Kalimantan\b", re.I), "Kalimantan Barat"),
    (re.compile(r"\bCentral Kalimantan\b", re.I), "Kalimantan Tengah"),
    (re.compile(r"\bSouth Tangerang\b", re.I), "Tangerang Selatan"),
    (re.compile(r"\bRiau Islands\b", re.I), "Kepulauan Riau"),
    (re.compile(r"\b(Special Region of Yogyakarta|Yogyakarta Special Region)\b", re.I),
     "DI Yogyakarta"),
    (re.compile(r"\bBangka Belitung Islands\b", re.I), "Kepulauan Bangka Belitung"),
]

# "X Regency" / "X District" adalah terjemahan Inggris untuk "Kabupaten X" /
# "Kecamatan X" — dibuang suffix-nya di _bersihkan_segmen, bukan diterjemahkan
# jadi frasa Indonesia (supaya "Tangerang Regency" tetap cocok ke kunci
# "tangerang" yang sudah ada di kamus, tanpa perlu entri "kabupaten tangerang"
# terpisah).
_SUFFIKS_ADMIN_INGGRIS = re.compile(
    r"\s+(Regency|District|City|Municipality)\s*$", re.I)

# Prefiks administratif yang dibuang sebelum pencocokan. Urutan penting: yang
# lebih panjang/spesifik duluan supaya tidak menyisakan sisa kata.
_PREFIKS_ADMIN = [
    # Glints/DIY: "Kapanewon Ngaglik" (kecamatan di kabupaten DIY) dan
    # "Kemantren Umbulharjo" (kecamatan di Kota Yogyakarta).
    re.compile(r"^(Kapanewon|Kemantren|Kecamatan|Kec\.)\s+", re.I),
    # Karir.com: "Prov. DKI-Jakarta", "Prov. Jawa-Barat".
    re.compile(r"^Prov(insi)?\.?\s+", re.I),
    re.compile(r"^Kota\s+Adm\.?\s+", re.I),
    re.compile(r"^Kabupaten\s+Adm\.?\s+", re.I),
    re.compile(r"^Kab\.\s+", re.I),
    re.compile(r"^Kabupaten\s+", re.I),
    re.compile(r"^Kota\s+", re.I),
]


# Suffix yang ditempelkan beberapa sumber tapi bukan bagian nama wilayah,
# mis. "Bekasi HO" (HO = Head Office, ditemukan di data Kalbe Farma).
_SUFFIKS_SAMPAH = re.compile(
    r"\s+(HO|Head\s*Office|Kantor\s*Pusat)\s*$", re.I)


_ARAH_INGGRIS = {
    "north": "Utara", "south": "Selatan", "east": "Timur", "west": "Barat",
    "central": "Tengah", "southeast": "Tenggara", "southwest": "Barat Daya",
}
_POLA_ARAH_DEPAN = re.compile(
    r"^(North|South|East|West|Central|Southeast|Southwest)\s+(.+)$", re.I)
_POLA_KURUNG = re.compile(r"\(([^)]+)\)")


def _bersihkan_segmen(teks: str) -> str:
    """Terjemahkan istilah Inggris, lalu buang prefiks/suffix admin & sampah."""
    # Kalibrr: "Central Kalimantan (Kalimantan Tengah)" -- nama Indonesia di
    # dalam kurung lebih bisa diandalkan daripada versi Inggrisnya.
    # Isi kurung hanya dipakai kalau memang nama wilayah yang dikenal;
    # "(Indonesia)", "(Offshore)", "(+2 lokasi lain)" dibuang saja.
    m = _POLA_KURUNG.search(teks)
    if m:
        dalam = m.group(1).strip()
        luar = _POLA_KURUNG.sub("", teks).strip()
        kunci_dalam = re.sub(r"\bSumatra\b", "Sumatera", dalam, flags=re.I).lower()
        if kunci_dalam in _PROVINSI_LANGSUNG or kunci_dalam in _KOTA_KE_PROVINSI:
            teks = dalam
        else:
            teks = luar or dalam
    # Ejaan "Sumatra" (Inggris) -> "Sumatera" (kunci kamus).
    teks = re.sub(r"\bSumatra\b", "Sumatera", teks, flags=re.I)
    for pola, ganti in _TERJEMAHAN_ARAH:
        teks = pola.sub(ganti, teks)
    # Arah Inggris di depan nama wilayah: "West Kotawaringin" ->
    # "Kotawaringin Barat", "Southeast Sulawesi" -> "Sulawesi Tenggara".
    m = _POLA_ARAH_DEPAN.match(teks.strip())
    if m:
        teks = f"{m.group(2)} {_ARAH_INGGRIS[m.group(1).lower()]}"
    for pola in _PREFIKS_ADMIN:
        teks = pola.sub("", teks)
    teks = _SUFFIKS_ADMIN_INGGRIS.sub("", teks)
    teks = _SUFFIKS_SAMPAH.sub("", teks)
    return teks.strip()


# --------------------------------------------------------------------------- #
# 2. Kota/Kabupaten -> Provinsi
# --------------------------------------------------------------------------- #
# Kunci dinormalisasi lowercase tanpa prefiks (mis. "surabaya", bukan
# "Kota Surabaya"). Dibangun dari data yang benar-benar muncul di database
# (query GROUP BY location, 50 teratas) ditambah kota/kabupaten besar lain
# per provinsi supaya kamusnya tidak cuma menutup yang kebetulan sudah masuk.
_KOTA_KE_PROVINSI: dict[str, str] = {
    # --- Jabodetabek (ditangani khusus, lihat _JABODETABEK di bawah, tapi
    # tetap didaftarkan di sini dengan provinsi aslinya untuk kelengkapan) ---
    "jakarta selatan": "DKI Jakarta", "jakarta pusat": "DKI Jakarta",
    "jakarta timur": "DKI Jakarta", "jakarta barat": "DKI Jakarta",
    "jakarta utara": "DKI Jakarta", "jakarta": "DKI Jakarta",
    "kepulauan seribu": "DKI Jakarta",
    "bogor": "Jawa Barat", "depok": "Jawa Barat",
    "tangerang": "Banten", "tangerang selatan": "Banten",
    "bekasi": "Jawa Barat",

    # --- Jawa Barat ---
    "bandung": "Jawa Barat", "kabupaten bandung": "Jawa Barat",
    "bandung barat": "Jawa Barat", "cimahi": "Jawa Barat",
    "karawang": "Jawa Barat", "purwakarta": "Jawa Barat",
    "tasikmalaya": "Jawa Barat", "sukabumi": "Jawa Barat",
    "cirebon": "Jawa Barat", "garut": "Jawa Barat", "subang": "Jawa Barat",
    "indramayu": "Jawa Barat", "kuningan": "Jawa Barat",
    "sumedang": "Jawa Barat", "cianjur": "Jawa Barat",
    "majalengka": "Jawa Barat", "ciamis": "Jawa Barat",
    "banjar": "Jawa Barat", "pangandaran": "Jawa Barat",

    # --- Banten ---
    "serang": "Banten", "cilegon": "Banten", "lebak": "Banten",
    "pandeglang": "Banten",

    # --- Jawa Tengah ---
    "semarang": "Jawa Tengah", "solo": "Jawa Tengah", "surakarta": "Jawa Tengah",
    "magelang": "Jawa Tengah", "salatiga": "Jawa Tengah", "tegal": "Jawa Tengah",
    "pekalongan": "Jawa Tengah", "kudus": "Jawa Tengah", "klaten": "Jawa Tengah",
    "sukoharjo": "Jawa Tengah", "purwokerto": "Jawa Tengah",
    "banyumas": "Jawa Tengah", "cilacap": "Jawa Tengah", "kebumen": "Jawa Tengah",
    "pati": "Jawa Tengah", "jepara": "Jawa Tengah", "demak": "Jawa Tengah",
    "boyolali": "Jawa Tengah", "sragen": "Jawa Tengah", "wonogiri": "Jawa Tengah",
    "batang": "Jawa Tengah", "pemalang": "Jawa Tengah", "brebes": "Jawa Tengah",
    "rembang": "Jawa Tengah", "blora": "Jawa Tengah", "grobogan": "Jawa Tengah",
    "temanggung": "Jawa Tengah", "wonosobo": "Jawa Tengah",
    "purbalingga": "Jawa Tengah", "banjarnegara": "Jawa Tengah",
    "karanganyar": "Jawa Tengah", "kendal": "Jawa Tengah",

    # --- DI Yogyakarta ---
    "yogyakarta": "DI Yogyakarta", "sleman": "DI Yogyakarta",
    "bantul": "DI Yogyakarta", "kulon progo": "DI Yogyakarta",
    "gunungkidul": "DI Yogyakarta", "gunung kidul": "DI Yogyakarta",

    # --- Jawa Timur ---
    "surabaya": "Jawa Timur", "malang": "Jawa Timur", "sidoarjo": "Jawa Timur",
    "gresik": "Jawa Timur", "kediri": "Jawa Timur", "madiun": "Jawa Timur",
    "mojokerto": "Jawa Timur", "pasuruan": "Jawa Timur", "probolinggo": "Jawa Timur",
    "jember": "Jawa Timur", "banyuwangi": "Jawa Timur", "blitar": "Jawa Timur",
    "tuban": "Jawa Timur", "lamongan": "Jawa Timur", "bojonegoro": "Jawa Timur",
    "jombang": "Jawa Timur", "nganjuk": "Jawa Timur", "madura": "Jawa Timur",
    "bangkalan": "Jawa Timur", "sumenep": "Jawa Timur", "pamekasan": "Jawa Timur",
    "batu": "Jawa Timur", "ponorogo": "Jawa Timur", "magetan": "Jawa Timur",
    "ngawi": "Jawa Timur", "pacitan": "Jawa Timur", "trenggalek": "Jawa Timur",
    "tulungagung": "Jawa Timur", "situbondo": "Jawa Timur", "bondowoso": "Jawa Timur",
    "lumajang": "Jawa Timur",

    # --- Sumatera ---
    "medan": "Sumatera Utara", "deli serdang": "Sumatera Utara",
    "binjai": "Sumatera Utara", "pematangsiantar": "Sumatera Utara",
    "padang": "Sumatera Barat", "bukittinggi": "Sumatera Barat",
    "payakumbuh": "Sumatera Barat", "padang panjang": "Sumatera Barat",
    "pekanbaru": "Riau", "dumai": "Riau", "batam": "Kepulauan Riau",
    "tanjung pinang": "Kepulauan Riau", "bintan": "Kepulauan Riau",
    "jambi": "Jambi", "palembang": "Sumatera Selatan",
    "prabumulih": "Sumatera Selatan", "lubuklinggau": "Sumatera Selatan",
    "bandar lampung": "Lampung", "metro": "Lampung",
    "lampung tengah": "Lampung", "lampung selatan": "Lampung",
    "lampung utara": "Lampung", "lampung timur": "Lampung",
    "lampung barat": "Lampung",
    "bengkulu": "Bengkulu", "pangkal pinang": "Kepulauan Bangka Belitung",
    "banda aceh": "Aceh", "lhokseumawe": "Aceh", "langsa": "Aceh",
    "aceh barat": "Aceh", "aceh besar": "Aceh", "aceh utara": "Aceh",
    "aceh selatan": "Aceh", "aceh timur": "Aceh", "aceh tengah": "Aceh",

    # --- Kalimantan ---
    "pontianak": "Kalimantan Barat", "singkawang": "Kalimantan Barat",
    "sanggau": "Kalimantan Barat", "ketapang": "Kalimantan Barat",
    "palangkaraya": "Kalimantan Tengah", "palangka raya": "Kalimantan Tengah",
    "banjarmasin": "Kalimantan Selatan", "banjarbaru": "Kalimantan Selatan",
    "balikpapan": "Kalimantan Timur", "samarinda": "Kalimantan Timur",
    "bontang": "Kalimantan Timur", "kutai kartanegara": "Kalimantan Timur",
    "tarakan": "Kalimantan Utara",

    # --- Sulawesi ---
    "makassar": "Sulawesi Selatan", "parepare": "Sulawesi Selatan",
    "maros": "Sulawesi Selatan", "pangkajene": "Sulawesi Selatan",
    "pangkajene kepulauan": "Sulawesi Selatan", "pangkep": "Sulawesi Selatan",
    "gowa": "Sulawesi Selatan",
    "manado": "Sulawesi Utara", "bitung": "Sulawesi Utara",
    "minahasa utara": "Sulawesi Utara", "minahasa": "Sulawesi Utara",
    "palu": "Sulawesi Tengah", "kendari": "Sulawesi Tenggara",
    "gorontalo": "Gorontalo", "mamuju": "Sulawesi Barat",

    # --- Bali & Nusa Tenggara ---
    "denpasar": "Bali", "badung": "Bali", "gianyar": "Bali",
    "tabanan": "Bali", "buleleng": "Bali", "karangasem": "Bali",
    "mataram": "Nusa Tenggara Barat", "lombok": "Nusa Tenggara Barat",
    "sumbawa": "Nusa Tenggara Barat", "bima": "Nusa Tenggara Barat",
    "kupang": "Nusa Tenggara Timur", "flores": "Nusa Tenggara Timur",

    # --- Indonesia Timur ---
    "ambon": "Maluku", "ternate": "Maluku Utara", "tidore": "Maluku Utara",
    "jayapura": "Papua", "sorong": "Papua Barat", "manokwari": "Papua Barat",
    "merauke": "Papua Selatan", "biak": "Papua",
}

# Kabupaten/kota tambahan, terutama di luar Jawa. Ditambahkan setelah
# pengecekan data nyata: Dealls & Kalibrr banyak menulis nama kabupaten
# ("Muara Enim Regency", "Kubu Raya", dst) yang tadinya tidak dikenali.
# setdefault: entri lama di atas TIDAK ditimpa.
_KABUPATEN_TAMBAHAN: dict[str, str] = {
    # Aceh
    "aceh besar": "Aceh",
    "aceh barat": "Aceh",
    "aceh barat daya": "Aceh",
    "aceh selatan": "Aceh",
    "aceh singkil": "Aceh",
    "aceh tamiang": "Aceh",
    "aceh tengah": "Aceh",
    "aceh tenggara": "Aceh",
    "aceh timur": "Aceh",
    "aceh utara": "Aceh",
    "aceh jaya": "Aceh",
    "bener meriah": "Aceh",
    "bireuen": "Aceh",
    "gayo lues": "Aceh",
    "nagan raya": "Aceh",
    "pidie": "Aceh",
    "pidie jaya": "Aceh",
    "simeulue": "Aceh",
    "langsa": "Aceh",
    "lhokseumawe": "Aceh",
    "sabang": "Aceh",
    "subulussalam": "Aceh",
    "banda aceh": "Aceh",
    "meulaboh": "Aceh",
    # Sumatera Utara
    "asahan": "Sumatera Utara",
    "batubara": "Sumatera Utara",
    "batu bara": "Sumatera Utara",
    "dairi": "Sumatera Utara",
    "deli serdang": "Sumatera Utara",
    "humbang hasundutan": "Sumatera Utara",
    "karo": "Sumatera Utara",
    "labuhanbatu": "Sumatera Utara",
    "labuhan batu": "Sumatera Utara",
    "labuhanbatu selatan": "Sumatera Utara",
    "labuhanbatu utara": "Sumatera Utara",
    "langkat": "Sumatera Utara",
    "mandailing natal": "Sumatera Utara",
    "nias": "Sumatera Utara",
    "nias selatan": "Sumatera Utara",
    "nias utara": "Sumatera Utara",
    "nias barat": "Sumatera Utara",
    "padang lawas": "Sumatera Utara",
    "padang lawas utara": "Sumatera Utara",
    "pakpak bharat": "Sumatera Utara",
    "samosir": "Sumatera Utara",
    "serdang bedagai": "Sumatera Utara",
    "simalungun": "Sumatera Utara",
    "tapanuli selatan": "Sumatera Utara",
    "tapanuli tengah": "Sumatera Utara",
    "tapanuli utara": "Sumatera Utara",
    "toba": "Sumatera Utara",
    "toba samosir": "Sumatera Utara",
    "binjai": "Sumatera Utara",
    "gunungsitoli": "Sumatera Utara",
    "padangsidimpuan": "Sumatera Utara",
    "padang sidempuan": "Sumatera Utara",
    "pematangsiantar": "Sumatera Utara",
    "pematang siantar": "Sumatera Utara",
    "sibolga": "Sumatera Utara",
    "tanjung balai": "Sumatera Utara",
    "tanjungbalai": "Sumatera Utara",
    "tebing tinggi": "Sumatera Utara",
    "kisaran": "Sumatera Utara",
    "rantau prapat": "Sumatera Utara",
    "rantauprapat": "Sumatera Utara",
    # Sumatera Barat
    "agam": "Sumatera Barat",
    "dharmasraya": "Sumatera Barat",
    "kepulauan mentawai": "Sumatera Barat",
    "lima puluh kota": "Sumatera Barat",
    "limapuluh kota": "Sumatera Barat",
    "padang pariaman": "Sumatera Barat",
    "pasaman": "Sumatera Barat",
    "pasaman barat": "Sumatera Barat",
    "pesisir selatan": "Sumatera Barat",
    "sijunjung": "Sumatera Barat",
    "solok": "Sumatera Barat",
    "solok selatan": "Sumatera Barat",
    "tanah datar": "Sumatera Barat",
    "bukittinggi": "Sumatera Barat",
    "padang panjang": "Sumatera Barat",
    "pariaman": "Sumatera Barat",
    "payakumbuh": "Sumatera Barat",
    "sawahlunto": "Sumatera Barat",
    # Riau
    "bengkalis": "Riau",
    "indragiri hilir": "Riau",
    "indragiri hulu": "Riau",
    "kampar": "Riau",
    "kepulauan meranti": "Riau",
    "kuantan singingi": "Riau",
    "pelalawan": "Riau",
    "rokan hilir": "Riau",
    "rokan hulu": "Riau",
    "siak": "Riau",
    "dumai": "Riau",
    # Kepulauan Riau
    "bintan": "Kepulauan Riau",
    "karimun": "Kepulauan Riau",
    "kepulauan anambas": "Kepulauan Riau",
    "anambas": "Kepulauan Riau",
    "lingga": "Kepulauan Riau",
    "natuna": "Kepulauan Riau",
    "tanjungpinang": "Kepulauan Riau",
    "tanjung pinang": "Kepulauan Riau",
    # Jambi
    "batanghari": "Jambi",
    "batang hari": "Jambi",
    "bungo": "Jambi",
    "kerinci": "Jambi",
    "merangin": "Jambi",
    "muaro jambi": "Jambi",
    "sarolangun": "Jambi",
    "tanjung jabung barat": "Jambi",
    "tanjung jabung timur": "Jambi",
    "tebo": "Jambi",
    "sungai penuh": "Jambi",
    # Sumatera Selatan
    "banyuasin": "Sumatera Selatan",
    "empat lawang": "Sumatera Selatan",
    "lahat": "Sumatera Selatan",
    "muara enim": "Sumatera Selatan",
    "musi banyuasin": "Sumatera Selatan",
    "musi rawas": "Sumatera Selatan",
    "musi rawas utara": "Sumatera Selatan",
    "ogan ilir": "Sumatera Selatan",
    "ogan komering ilir": "Sumatera Selatan",
    "ogan komering ulu": "Sumatera Selatan",
    "ogan komering ulu selatan": "Sumatera Selatan",
    "ogan komering ulu timur": "Sumatera Selatan",
    "penukal abab lematang ilir": "Sumatera Selatan",
    "lubuklinggau": "Sumatera Selatan",
    "lubuk linggau": "Sumatera Selatan",
    "pagar alam": "Sumatera Selatan",
    "pagaralam": "Sumatera Selatan",
    "prabumulih": "Sumatera Selatan",
    "baturaja": "Sumatera Selatan",
    # Kepulauan Bangka Belitung
    "bangka": "Kepulauan Bangka Belitung",
    "bangka barat": "Kepulauan Bangka Belitung",
    "bangka selatan": "Kepulauan Bangka Belitung",
    "bangka tengah": "Kepulauan Bangka Belitung",
    "belitung": "Kepulauan Bangka Belitung",
    "belitung timur": "Kepulauan Bangka Belitung",
    "pangkalpinang": "Kepulauan Bangka Belitung",
    "pangkal pinang": "Kepulauan Bangka Belitung",
    # Bengkulu
    "bengkulu selatan": "Bengkulu",
    "bengkulu tengah": "Bengkulu",
    "bengkulu utara": "Bengkulu",
    "kaur": "Bengkulu",
    "kepahiang": "Bengkulu",
    "lebong": "Bengkulu",
    "mukomuko": "Bengkulu",
    "muko muko": "Bengkulu",
    "rejang lebong": "Bengkulu",
    "seluma": "Bengkulu",
    # Lampung
    "lampung barat": "Lampung",
    "lampung selatan": "Lampung",
    "lampung tengah": "Lampung",
    "lampung timur": "Lampung",
    "lampung utara": "Lampung",
    "mesuji": "Lampung",
    "pesawaran": "Lampung",
    "pesisir barat": "Lampung",
    "pringsewu": "Lampung",
    "tanggamus": "Lampung",
    "tulang bawang": "Lampung",
    "tulangbawang": "Lampung",
    "tulang bawang barat": "Lampung",
    "way kanan": "Lampung",
    "metro": "Lampung",
    # Jawa Barat
    "bandung barat": "Jawa Barat",
    "ciamis": "Jawa Barat",
    "cianjur": "Jawa Barat",
    "garut": "Jawa Barat",
    "indramayu": "Jawa Barat",
    "karawang": "Jawa Barat",
    "kuningan": "Jawa Barat",
    "majalengka": "Jawa Barat",
    "pangandaran": "Jawa Barat",
    "purwakarta": "Jawa Barat",
    "subang": "Jawa Barat",
    "sukabumi": "Jawa Barat",
    "sumedang": "Jawa Barat",
    "tasikmalaya": "Jawa Barat",
    "cimahi": "Jawa Barat",
    "cirebon": "Jawa Barat",
    # Jawa Tengah
    "banjarnegara": "Jawa Tengah",
    "banyumas": "Jawa Tengah",
    "batang": "Jawa Tengah",
    "blora": "Jawa Tengah",
    "boyolali": "Jawa Tengah",
    "brebes": "Jawa Tengah",
    "cilacap": "Jawa Tengah",
    "demak": "Jawa Tengah",
    "grobogan": "Jawa Tengah",
    "jepara": "Jawa Tengah",
    "karanganyar": "Jawa Tengah",
    "kebumen": "Jawa Tengah",
    "kendal": "Jawa Tengah",
    "klaten": "Jawa Tengah",
    "kudus": "Jawa Tengah",
    "magelang": "Jawa Tengah",
    "pati": "Jawa Tengah",
    "pekalongan": "Jawa Tengah",
    "pemalang": "Jawa Tengah",
    "purbalingga": "Jawa Tengah",
    "purworejo": "Jawa Tengah",
    "rembang": "Jawa Tengah",
    "sragen": "Jawa Tengah",
    "sukoharjo": "Jawa Tengah",
    "temanggung": "Jawa Tengah",
    "wonogiri": "Jawa Tengah",
    "wonosobo": "Jawa Tengah",
    "salatiga": "Jawa Tengah",
    "tegal": "Jawa Tengah",
    "purwokerto": "Jawa Tengah",
    # Jawa Timur
    "bangkalan": "Jawa Timur",
    "banyuwangi": "Jawa Timur",
    "blitar": "Jawa Timur",
    "bojonegoro": "Jawa Timur",
    "bondowoso": "Jawa Timur",
    "gresik": "Jawa Timur",
    "jember": "Jawa Timur",
    "jombang": "Jawa Timur",
    "kediri": "Jawa Timur",
    "lamongan": "Jawa Timur",
    "lumajang": "Jawa Timur",
    "madiun": "Jawa Timur",
    "magetan": "Jawa Timur",
    "malang": "Jawa Timur",
    "mojokerto": "Jawa Timur",
    "nganjuk": "Jawa Timur",
    "ngawi": "Jawa Timur",
    "pacitan": "Jawa Timur",
    "pamekasan": "Jawa Timur",
    "pasuruan": "Jawa Timur",
    "ponorogo": "Jawa Timur",
    "probolinggo": "Jawa Timur",
    "sampang": "Jawa Timur",
    "sidoarjo": "Jawa Timur",
    "situbondo": "Jawa Timur",
    "sumenep": "Jawa Timur",
    "trenggalek": "Jawa Timur",
    "tuban": "Jawa Timur",
    "tulungagung": "Jawa Timur",
    "batu": "Jawa Timur",
    "sukorejo": "Jawa Timur",
    "sukoredjo": "Jawa Timur",
    # Banten
    "lebak": "Banten",
    "pandeglang": "Banten",
    "serang": "Banten",
    "cilegon": "Banten",
    # DI Yogyakarta
    "bantul": "DI Yogyakarta",
    "gunungkidul": "DI Yogyakarta",
    "gunung kidul": "DI Yogyakarta",
    "kulon progo": "DI Yogyakarta",
    "kulonprogo": "DI Yogyakarta",
    "sleman": "DI Yogyakarta",
    # Bali
    "badung": "Bali",
    "bangli": "Bali",
    "buleleng": "Bali",
    "gianyar": "Bali",
    "jembrana": "Bali",
    "karangasem": "Bali",
    "klungkung": "Bali",
    "tabanan": "Bali",
    "denpasar": "Bali",
    # Nusa Tenggara Barat
    "bima": "Nusa Tenggara Barat",
    "dompu": "Nusa Tenggara Barat",
    "lombok barat": "Nusa Tenggara Barat",
    "lombok tengah": "Nusa Tenggara Barat",
    "lombok timur": "Nusa Tenggara Barat",
    "lombok utara": "Nusa Tenggara Barat",
    "sumbawa": "Nusa Tenggara Barat",
    "sumbawa barat": "Nusa Tenggara Barat",
    "mataram": "Nusa Tenggara Barat",
    # Nusa Tenggara Timur
    "alor": "Nusa Tenggara Timur",
    "belu": "Nusa Tenggara Timur",
    "ende": "Nusa Tenggara Timur",
    "flores timur": "Nusa Tenggara Timur",
    "kupang": "Nusa Tenggara Timur",
    "lembata": "Nusa Tenggara Timur",
    "malaka": "Nusa Tenggara Timur",
    "manggarai": "Nusa Tenggara Timur",
    "manggarai barat": "Nusa Tenggara Timur",
    "manggarai timur": "Nusa Tenggara Timur",
    "nagekeo": "Nusa Tenggara Timur",
    "ngada": "Nusa Tenggara Timur",
    "rote ndao": "Nusa Tenggara Timur",
    "sabu raijua": "Nusa Tenggara Timur",
    "sikka": "Nusa Tenggara Timur",
    "sumba barat": "Nusa Tenggara Timur",
    "sumba barat daya": "Nusa Tenggara Timur",
    "sumba tengah": "Nusa Tenggara Timur",
    "sumba timur": "Nusa Tenggara Timur",
    "timor tengah selatan": "Nusa Tenggara Timur",
    "timor tengah utara": "Nusa Tenggara Timur",
    "labuan bajo": "Nusa Tenggara Timur",
    "maumere": "Nusa Tenggara Timur",
    # Kalimantan Barat
    "bengkayang": "Kalimantan Barat",
    "kapuas hulu": "Kalimantan Barat",
    "kayong utara": "Kalimantan Barat",
    "ketapang": "Kalimantan Barat",
    "kubu raya": "Kalimantan Barat",
    "landak": "Kalimantan Barat",
    "melawi": "Kalimantan Barat",
    "mempawah": "Kalimantan Barat",
    "sambas": "Kalimantan Barat",
    "sanggau": "Kalimantan Barat",
    "sekadau": "Kalimantan Barat",
    "sintang": "Kalimantan Barat",
    "pontianak": "Kalimantan Barat",
    "singkawang": "Kalimantan Barat",
    # Kalimantan Tengah
    "barito selatan": "Kalimantan Tengah",
    "barito timur": "Kalimantan Tengah",
    "barito utara": "Kalimantan Tengah",
    "gunung mas": "Kalimantan Tengah",
    "kapuas": "Kalimantan Tengah",
    "katingan": "Kalimantan Tengah",
    "kotawaringin barat": "Kalimantan Tengah",
    "kotawaringin timur": "Kalimantan Tengah",
    "lamandau": "Kalimantan Tengah",
    "murung raya": "Kalimantan Tengah",
    "pulang pisau": "Kalimantan Tengah",
    "sukamara": "Kalimantan Tengah",
    "seruyan": "Kalimantan Tengah",
    "palangka raya": "Kalimantan Tengah",
    "palangkaraya": "Kalimantan Tengah",
    "sampit": "Kalimantan Tengah",
    "pangkalan bun": "Kalimantan Tengah",
    # Kalimantan Selatan
    "balangan": "Kalimantan Selatan",
    "barito kuala": "Kalimantan Selatan",
    "hulu sungai selatan": "Kalimantan Selatan",
    "hulu sungai tengah": "Kalimantan Selatan",
    "hulu sungai utara": "Kalimantan Selatan",
    "kotabaru": "Kalimantan Selatan",
    "kota baru": "Kalimantan Selatan",
    "tabalong": "Kalimantan Selatan",
    "tanah bumbu": "Kalimantan Selatan",
    "tanah laut": "Kalimantan Selatan",
    "tapin": "Kalimantan Selatan",
    "banjarbaru": "Kalimantan Selatan",
    "banjarmasin": "Kalimantan Selatan",
    "batulicin": "Kalimantan Selatan",
    # Kalimantan Timur
    "berau": "Kalimantan Timur",
    "kutai barat": "Kalimantan Timur",
    "kutai kartanegara": "Kalimantan Timur",
    "kutai timur": "Kalimantan Timur",
    "mahakam ulu": "Kalimantan Timur",
    "paser": "Kalimantan Timur",
    "penajam paser utara": "Kalimantan Timur",
    "balikpapan": "Kalimantan Timur",
    "bontang": "Kalimantan Timur",
    "samarinda": "Kalimantan Timur",
    "sangatta": "Kalimantan Timur",
    "tenggarong": "Kalimantan Timur",
    # Kalimantan Utara
    "bulungan": "Kalimantan Utara",
    "malinau": "Kalimantan Utara",
    "nunukan": "Kalimantan Utara",
    "tana tidung": "Kalimantan Utara",
    "tarakan": "Kalimantan Utara",
    "tanjung selor": "Kalimantan Utara",
    # Sulawesi Utara
    "bolaang mongondow": "Sulawesi Utara",
    "bolaang mongondow utara": "Sulawesi Utara",
    "bolaang mongondow selatan": "Sulawesi Utara",
    "bolaang mongondow timur": "Sulawesi Utara",
    "kepulauan sangihe": "Sulawesi Utara",
    "kepulauan talaud": "Sulawesi Utara",
    "kepulauan siau tagulandang biaro": "Sulawesi Utara",
    "minahasa": "Sulawesi Utara",
    "minahasa selatan": "Sulawesi Utara",
    "minahasa tenggara": "Sulawesi Utara",
    "minahasa utara": "Sulawesi Utara",
    "bitung": "Sulawesi Utara",
    "kotamobagu": "Sulawesi Utara",
    "manado": "Sulawesi Utara",
    "tomohon": "Sulawesi Utara",
    # Gorontalo
    "boalemo": "Gorontalo",
    "bone bolango": "Gorontalo",
    "gorontalo utara": "Gorontalo",
    "pohuwato": "Gorontalo",
    # Sulawesi Tengah
    "banggai": "Sulawesi Tengah",
    "banggai kepulauan": "Sulawesi Tengah",
    "banggai laut": "Sulawesi Tengah",
    "buol": "Sulawesi Tengah",
    "donggala": "Sulawesi Tengah",
    "morowali": "Sulawesi Tengah",
    "morowali utara": "Sulawesi Tengah",
    "parigi moutong": "Sulawesi Tengah",
    "poso": "Sulawesi Tengah",
    "sigi": "Sulawesi Tengah",
    "tojo una-una": "Sulawesi Tengah",
    "tolitoli": "Sulawesi Tengah",
    "toli-toli": "Sulawesi Tengah",
    "palu": "Sulawesi Tengah",
    "luwuk": "Sulawesi Tengah",
    # Sulawesi Barat
    "majene": "Sulawesi Barat",
    "mamasa": "Sulawesi Barat",
    "mamuju": "Sulawesi Barat",
    "mamuju tengah": "Sulawesi Barat",
    "pasangkayu": "Sulawesi Barat",
    "polewali mandar": "Sulawesi Barat",
    # Sulawesi Selatan
    "bantaeng": "Sulawesi Selatan",
    "barru": "Sulawesi Selatan",
    "bone": "Sulawesi Selatan",
    "bulukumba": "Sulawesi Selatan",
    "enrekang": "Sulawesi Selatan",
    "gowa": "Sulawesi Selatan",
    "jeneponto": "Sulawesi Selatan",
    "kepulauan selayar": "Sulawesi Selatan",
    "selayar": "Sulawesi Selatan",
    "luwu": "Sulawesi Selatan",
    "luwu timur": "Sulawesi Selatan",
    "luwu utara": "Sulawesi Selatan",
    "maros": "Sulawesi Selatan",
    "pangkajene dan kepulauan": "Sulawesi Selatan",
    "pangkep": "Sulawesi Selatan",
    "pinrang": "Sulawesi Selatan",
    "sidenreng rappang": "Sulawesi Selatan",
    "sidrap": "Sulawesi Selatan",
    "sinjai": "Sulawesi Selatan",
    "soppeng": "Sulawesi Selatan",
    "takalar": "Sulawesi Selatan",
    "tana toraja": "Sulawesi Selatan",
    "toraja utara": "Sulawesi Selatan",
    "wajo": "Sulawesi Selatan",
    "makassar": "Sulawesi Selatan",
    "palopo": "Sulawesi Selatan",
    "parepare": "Sulawesi Selatan",
    "pare pare": "Sulawesi Selatan",
    "sengkang": "Sulawesi Selatan",
    # Sulawesi Tenggara
    "bombana": "Sulawesi Tenggara",
    "buton": "Sulawesi Tenggara",
    "buton selatan": "Sulawesi Tenggara",
    "buton tengah": "Sulawesi Tenggara",
    "buton utara": "Sulawesi Tenggara",
    "kolaka": "Sulawesi Tenggara",
    "kolaka timur": "Sulawesi Tenggara",
    "kolaka utara": "Sulawesi Tenggara",
    "konawe": "Sulawesi Tenggara",
    "konawe kepulauan": "Sulawesi Tenggara",
    "konawe selatan": "Sulawesi Tenggara",
    "konawe utara": "Sulawesi Tenggara",
    "muna": "Sulawesi Tenggara",
    "muna barat": "Sulawesi Tenggara",
    "wakatobi": "Sulawesi Tenggara",
    "baubau": "Sulawesi Tenggara",
    "bau bau": "Sulawesi Tenggara",
    "kendari": "Sulawesi Tenggara",
    # Maluku
    "buru": "Maluku",
    "buru selatan": "Maluku",
    "kepulauan aru": "Maluku",
    "kepulauan tanimbar": "Maluku",
    "maluku tengah": "Maluku",
    "maluku tenggara": "Maluku",
    "seram bagian barat": "Maluku",
    "seram bagian timur": "Maluku",
    "ambon": "Maluku",
    "tual": "Maluku",
    # Maluku Utara
    "halmahera barat": "Maluku Utara",
    "halmahera selatan": "Maluku Utara",
    "halmahera tengah": "Maluku Utara",
    "halmahera timur": "Maluku Utara",
    "halmahera utara": "Maluku Utara",
    "kepulauan sula": "Maluku Utara",
    "pulau morotai": "Maluku Utara",
    "ternate": "Maluku Utara",
    "tidore kepulauan": "Maluku Utara",
    "tidore": "Maluku Utara",
    "weda": "Maluku Utara",
    # Papua
    "jayapura": "Papua",
    "biak numfor": "Papua",
    "biak": "Papua",
    "keerom": "Papua",
    "sarmi": "Papua",
    "waropen": "Papua",
    "kepulauan yapen": "Papua",
    "mamberamo raya": "Papua",
    # Papua Tengah
    "mimika": "Papua Tengah",
    "timika": "Papua Tengah",
    "nabire": "Papua Tengah",
    "paniai": "Papua Tengah",
    "dogiyai": "Papua Tengah",
    "deiyai": "Papua Tengah",
    "intan jaya": "Papua Tengah",
    "puncak": "Papua Tengah",
    "puncak jaya": "Papua Tengah",
    # Papua Selatan
    "merauke": "Papua Selatan",
    "boven digoel": "Papua Selatan",
    "mappi": "Papua Selatan",
    "asmat": "Papua Selatan",
    # Papua Barat
    "manokwari": "Papua Barat",
    "manokwari selatan": "Papua Barat",
    "fakfak": "Papua Barat",
    "kaimana": "Papua Barat",
    "teluk bintuni": "Papua Barat",
    "teluk wondama": "Papua Barat",
    "pegunungan arfak": "Papua Barat",
    # Papua Barat Daya
    "sorong": "Papua Barat Daya",
    "sorong selatan": "Papua Barat Daya",
    "raja ampat": "Papua Barat Daya",
    "maybrat": "Papua Barat Daya",
    "tambrauw": "Papua Barat Daya",
    # Papua Pegunungan
    "jayawijaya": "Papua Pegunungan",
    "wamena": "Papua Pegunungan",
    "lanny jaya": "Papua Pegunungan",
    "tolikara": "Papua Pegunungan",
    "yahukimo": "Papua Pegunungan",
    "pegunungan bintang": "Papua Pegunungan",
}
for _k, _v in _KABUPATEN_TAMBAHAN.items():
    _KOTA_KE_PROVINSI.setdefault(_k, _v)

# Nama PROVINSI itu sendiri sebagai kunci langsung. Beberapa sumber (KitaLulus,
# Kalibrr) kadang cuma menulis nama provinsi polos ("Bali", "Riau") tanpa kota
# spesifik — kalau cuma mengandalkan kamus kota/kabupaten di atas, provinsi
# yang ditulis sendirian ini tidak akan pernah cocok.
_PROVINSI_LANGSUNG: dict[str, str] = {
    "dki jakarta": "DKI Jakarta", "jakarta raya": "DKI Jakarta",
    "jawa barat": "Jawa Barat", "jawa tengah": "Jawa Tengah",
    "jawa timur": "Jawa Timur", "banten": "Banten",
    "di yogyakarta": "DI Yogyakarta", "yogyakarta": "DI Yogyakarta",
    "daerah istimewa yogyakarta": "DI Yogyakarta",
    "aceh": "Aceh", "sumatera utara": "Sumatera Utara",
    "sumatera barat": "Sumatera Barat", "riau": "Riau",
    "kepulauan riau": "Kepulauan Riau", "jambi": "Jambi",
    "sumatera selatan": "Sumatera Selatan", "bengkulu": "Bengkulu",
    "lampung": "Lampung", "kepulauan bangka belitung": "Kepulauan Bangka Belitung",
    "bangka belitung": "Kepulauan Bangka Belitung",
    "kalimantan barat": "Kalimantan Barat", "kalimantan tengah": "Kalimantan Tengah",
    "kalimantan selatan": "Kalimantan Selatan", "kalimantan timur": "Kalimantan Timur",
    "kalimantan utara": "Kalimantan Utara",
    "sulawesi utara": "Sulawesi Utara", "sulawesi tengah": "Sulawesi Tengah",
    "sulawesi selatan": "Sulawesi Selatan", "sulawesi tenggara": "Sulawesi Tenggara",
    "gorontalo": "Gorontalo", "sulawesi barat": "Sulawesi Barat",
    "bali": "Bali", "nusa tenggara barat": "Nusa Tenggara Barat",
    "nusa tenggara timur": "Nusa Tenggara Timur",
    "maluku": "Maluku", "maluku utara": "Maluku Utara",
    "papua": "Papua", "papua barat": "Papua Barat",
    "papua selatan": "Papua Selatan", "papua tengah": "Papua Tengah",
    "papua pegunungan": "Papua Pegunungan", "papua barat daya": "Papua Barat Daya",
}

# Kecamatan/kawasan yang levelnya di BAWAH kota/kabupaten, tapi cukup sering
# dipakai sebagai lokasi (terutama oleh Kalibrr/KitaLulus) sehingga perlu
# dipetakan LANGSUNG ke region — kita tidak perlu tahu kabupaten resminya,
# cukup tahu ini bagian dari kawasan Jabodetabek.
_KECAMATAN_JABODETABEK = {
    # Jakarta Utara
    "penjaringan", "koja", "cilincing", "pademangan", "tanjung priok",
    "kelapa gading",
    # Jakarta Barat
    "cengkareng", "grogol petamburan", "kebon jeruk", "kalideres",
    "kembangan", "palmerah", "taman sari", "tambora",
    # Jakarta Selatan
    "setiabudi", "kebayoran baru", "kebayoran lama", "pancoran",
    "tebet", "mampang prapatan", "pasar minggu", "cilandak",
    "jagakarsa", "pesanggrahan",
    # Jakarta Pusat
    "menteng", "tanah abang", "gambir", "sawah besar", "senen",
    "cempaka putih", "johar baru", "kemayoran",
    # Jakarta Timur
    "cakung", "duren sawit", "jatinegara", "kramat jati", "makasar",
    "matraman", "pasar rebo", "pulo gadung", "ciracas",
    # Tangerang & sekitarnya
    "pinang", "cipondoh", "karawaci", "cikupa", "curug", "legok",
    "serpong", "bsd", "cisauk", "pamulang", "ciputat",
    # Bekasi & kawasan industri
    "cikarang", "cikarang pusat", "cikarang utara", "cikarang selatan",
    "cikarang barat", "cikarang timur", "cibitung", "tambun",
    "jababeka", "lippo cikarang",
}

# Kota/kabupaten yang SELALU jadi region "jabodetabek", terlepas dari
# provinsi resminya. Diperiksa SEBELUM pemetaan provinsi->region biasa.
_JABODETABEK = {
    "jakarta selatan", "jakarta pusat", "jakarta timur", "jakarta barat",
    "jakarta utara", "jakarta", "kepulauan seribu",
    "bogor", "depok", "tangerang", "tangerang selatan", "bekasi",
}

# --------------------------------------------------------------------------- #
# 3. Provinsi -> Region
# --------------------------------------------------------------------------- #
_PROVINSI_KE_REGION: dict[str, str] = {
    "dki jakarta": "jabodetabek",  # fallback; harusnya sudah ketangkap _JABODETABEK

    "jawa barat": "jawa", "banten": "jawa", "jawa tengah": "jawa",
    "di yogyakarta": "jawa", "jawa timur": "jawa",

    "aceh": "sumatera", "sumatera utara": "sumatera", "sumatera barat": "sumatera",
    "riau": "sumatera", "kepulauan riau": "sumatera", "jambi": "sumatera",
    "sumatera selatan": "sumatera", "bengkulu": "sumatera",
    "lampung": "sumatera", "kepulauan bangka belitung": "sumatera",

    "kalimantan barat": "kalimantan", "kalimantan tengah": "kalimantan",
    "kalimantan selatan": "kalimantan", "kalimantan timur": "kalimantan",
    "kalimantan utara": "kalimantan",

    "sulawesi utara": "sulawesi", "sulawesi tengah": "sulawesi",
    "sulawesi selatan": "sulawesi", "sulawesi tenggara": "sulawesi",
    "gorontalo": "sulawesi", "sulawesi barat": "sulawesi",

    "bali": "bali_nusra", "nusa tenggara barat": "bali_nusra",
    "nusa tenggara timur": "bali_nusra",

    "maluku": "indonesia_timur", "maluku utara": "indonesia_timur",
    "papua": "indonesia_timur", "papua barat": "indonesia_timur",
    "papua selatan": "indonesia_timur", "papua tengah": "indonesia_timur",
    "papua pegunungan": "indonesia_timur", "papua barat daya": "indonesia_timur",
}

# Kecamatan. Glints hanya mengirim nama KECAMATAN ("Pagedangan",
# "Coblong", "Kapanewon Ngaglik") tanpa kota/provinsi, jadi dipetakan
# langsung. Nama kecamatan yang dipakai di dua daerah berbeda dipetakan ke
# yang paling umum muncul di lowongan; region-nya hampir selalu sama.
_KECAMATAN_JABODETABEK.update({
    "pagedangan",
    "pondok aren",
    "kelapa dua",
    "kosambi",
    "benda",
    "beji",
    "pancoran mas",
    "jatisampurna",
    "gunung putri",
    "tambun selatan",
    "tambun utara",
    "serpong utara",
    "ciputat timur",
    "setu",
    "karang tengah",
    "larangan",
    "ciledug",
    "batuceper",
    "neglasari",
    "periuk",
    "jatiuwung",
    "cibodas",
    "cikokol",
    "tangerang kota",
    "rajeg",
    "sepatan",
    "teluknaga",
    "pasar kemis",
    "balaraja",
    "tigaraksa",
    "panongan",
    "jatiuwung",
    "bekasi barat",
    "bekasi timur",
    "bekasi selatan",
    "bekasi utara",
    "medan satria",
    "rawalumbu",
    "bantar gebang",
    "bantargebang",
    "mustika jaya",
    "jatiasih",
    "pondok gede",
    "pondok melati",
    "jatisampurna",
    "babelan",
    "tarumajaya",
    "cibarusah",
    "serang baru",
    "cimanggis",
    "sukmajaya",
    "cilodong",
    "tapos",
    "sawangan",
    "bojongsari",
    "cinere",
    "limo",
    "cipayung",
    "cibinong",
    "citeureup",
    "bojonggede",
    "bojong gede",
    "babakan madang",
    "sentul",
    "cileungsi",
    "klapanunggal",
    "dramaga",
    "ciawi",
    "megamendung",
    "cisarua",
    "tanah sareal",
    "bogor barat",
    "bogor timur",
    "bogor selatan",
    "bogor tengah",
    "bogor utara",
    "parung",
    "gunung sindur",
    "ciomas",
    "cibubur",
    "kemang",
    "ciampea",
    "jonggol",
    "kebon jeruk",
    "cempaka putih",
    "kalibata",
    "kuningan",
    "sunter",
    "pluit",
    "kelapa gading barat",
    "pulogadung",
    "pulo gebang",
    "rawamangun",
    "cawang",
    "cipete",
    "pondok indah",
    "puri indah",
    "alam sutera",
    "gading serpong",
    "bintaro",
    "lippo karawaci",
})
_KECAMATAN_KE_PROVINSI: dict[str, str] = {
    # Jawa Barat
    "coblong": "Jawa Barat",
    "cicendo": "Jawa Barat",
    "sukajadi": "Jawa Barat",
    "regol": "Jawa Barat",
    "sumur bandung": "Jawa Barat",
    "bojongloa kidul": "Jawa Barat",
    "bojongloa kaler": "Jawa Barat",
    "cibeunying kaler": "Jawa Barat",
    "cibeunying kidul": "Jawa Barat",
    "bandung wetan": "Jawa Barat",
    "bandung kulon": "Jawa Barat",
    "bandung kidul": "Jawa Barat",
    "lengkong": "Jawa Barat",
    "batununggal": "Jawa Barat",
    "kiaracondong": "Jawa Barat",
    "antapani": "Jawa Barat",
    "arcamanik": "Jawa Barat",
    "buahbatu": "Jawa Barat",
    "buah batu": "Jawa Barat",
    "rancasari": "Jawa Barat",
    "gedebage": "Jawa Barat",
    "cibiru": "Jawa Barat",
    "ujungberung": "Jawa Barat",
    "ujung berung": "Jawa Barat",
    "andir": "Jawa Barat",
    "astanaanyar": "Jawa Barat",
    "astana anyar": "Jawa Barat",
    "babakan ciparay": "Jawa Barat",
    "cidadap": "Jawa Barat",
    "sukasari": "Jawa Barat",
    "mandalajati": "Jawa Barat",
    "panyileukan": "Jawa Barat",
    "cinambo": "Jawa Barat",
    "cimahi selatan": "Jawa Barat",
    "cimahi utara": "Jawa Barat",
    "cimahi tengah": "Jawa Barat",
    "lembang": "Jawa Barat",
    "dayeuhkolot": "Jawa Barat",
    "baleendah": "Jawa Barat",
    "margahayu": "Jawa Barat",
    "soreang": "Jawa Barat",
    "cikarang": "Jawa Barat",
    "jatinangor": "Jawa Barat",
    "cikampek": "Jawa Barat",
    "telukjambe": "Jawa Barat",
    "telukjambe timur": "Jawa Barat",
    "karawang barat": "Jawa Barat",
    "karawang timur": "Jawa Barat",
    "cirebon kota": "Jawa Barat",
    # Jawa Timur
    "sambikerep": "Jawa Timur",
    "asem rowo": "Jawa Timur",
    "asemrowo": "Jawa Timur",
    "mulyorejo": "Jawa Timur",
    "sukolilo": "Jawa Timur",
    "genteng": "Jawa Timur",
    "gubeng": "Jawa Timur",
    "tegalsari": "Jawa Timur",
    "wonokromo": "Jawa Timur",
    "rungkut": "Jawa Timur",
    "tenggilis mejoyo": "Jawa Timur",
    "wiyung": "Jawa Timur",
    "lakarsantri": "Jawa Timur",
    "benowo": "Jawa Timur",
    "pakal": "Jawa Timur",
    "tandes": "Jawa Timur",
    "sukomanunggal": "Jawa Timur",
    "dukuh pakis": "Jawa Timur",
    "sawahan": "Jawa Timur",
    "bubutan": "Jawa Timur",
    "simokerto": "Jawa Timur",
    "pabean cantian": "Jawa Timur",
    "semampir": "Jawa Timur",
    "krembangan": "Jawa Timur",
    "kenjeran": "Jawa Timur",
    "bulak": "Jawa Timur",
    "tambaksari": "Jawa Timur",
    "wonocolo": "Jawa Timur",
    "gayungan": "Jawa Timur",
    "jambangan": "Jawa Timur",
    "karang pilang": "Jawa Timur",
    "gunung anyar": "Jawa Timur",
    "waru": "Jawa Timur",
    "taman": "Jawa Timur",
    "buduran": "Jawa Timur",
    "gedangan": "Jawa Timur",
    "candi": "Jawa Timur",
    "porong": "Jawa Timur",
    "driyorejo": "Jawa Timur",
    "kebomas": "Jawa Timur",
    "manyar": "Jawa Timur",
    "lowokwaru": "Jawa Timur",
    "klojen": "Jawa Timur",
    "blimbing": "Jawa Timur",
    "sukun": "Jawa Timur",
    "kedungkandang": "Jawa Timur",
    # Jawa Tengah
    "semarang barat": "Jawa Tengah",
    "semarang tengah": "Jawa Tengah",
    "semarang timur": "Jawa Tengah",
    "semarang utara": "Jawa Tengah",
    "semarang selatan": "Jawa Tengah",
    "banyumanik": "Jawa Tengah",
    "tembalang": "Jawa Tengah",
    "candisari": "Jawa Tengah",
    "gajahmungkur": "Jawa Tengah",
    "gajah mungkur": "Jawa Tengah",
    "pedurungan": "Jawa Tengah",
    "genuk": "Jawa Tengah",
    "gayamsari": "Jawa Tengah",
    "ngaliyan": "Jawa Tengah",
    "mijen": "Jawa Tengah",
    "tugu": "Jawa Tengah",
    "gunungpati": "Jawa Tengah",
    "ungaran": "Jawa Tengah",
    "laweyan": "Jawa Tengah",
    "banjarsari": "Jawa Tengah",
    "jebres": "Jawa Tengah",
    "pasar kliwon": "Jawa Tengah",
    "serengan": "Jawa Tengah",
    "kartasura": "Jawa Tengah",
    # DI Yogyakarta
    "umbulharjo": "DI Yogyakarta",
    "gondokusuman": "DI Yogyakarta",
    "jetis": "DI Yogyakarta",
    "tegalrejo": "DI Yogyakarta",
    "mergangsan": "DI Yogyakarta",
    "wirobrajan": "DI Yogyakarta",
    "gedongtengen": "DI Yogyakarta",
    "danurejan": "DI Yogyakarta",
    "kraton": "DI Yogyakarta",
    "mantrijeron": "DI Yogyakarta",
    "ngampilan": "DI Yogyakarta",
    "pakualaman": "DI Yogyakarta",
    "gondomanan": "DI Yogyakarta",
    "kotagede": "DI Yogyakarta",
    "ngaglik": "DI Yogyakarta",
    "mlati": "DI Yogyakarta",
    "gamping": "DI Yogyakarta",
    "banguntapan": "DI Yogyakarta",
    "sewon": "DI Yogyakarta",
    "kasihan": "DI Yogyakarta",
    "kalasan": "DI Yogyakarta",
    "berbah": "DI Yogyakarta",
    "ngemplak": "DI Yogyakarta",
    "godean": "DI Yogyakarta",
    "sleman": "DI Yogyakarta",
    "seyegan": "DI Yogyakarta",
    "prambanan": "DI Yogyakarta",
    "piyungan": "DI Yogyakarta",
    "bantul": "DI Yogyakarta",
    # Bali
    "kuta": "Bali",
    "kuta utara": "Bali",
    "kuta selatan": "Bali",
    "mengwi": "Bali",
    "abiansemal": "Bali",
    "ubud": "Bali",
    "sukawati": "Bali",
    "denpasar barat": "Bali",
    "denpasar selatan": "Bali",
    "denpasar timur": "Bali",
    "denpasar utara": "Bali",
    "jimbaran": "Bali",
    "nusa dua": "Bali",
    "canggu": "Bali",
    "seminyak": "Bali",
    "sanur": "Bali",
    # Kepulauan Riau
    "batam kota": "Kepulauan Riau",
    "batu aji": "Kepulauan Riau",
    "sekupang": "Kepulauan Riau",
    "lubuk baja": "Kepulauan Riau",
    "bengkong": "Kepulauan Riau",
    "nongsa": "Kepulauan Riau",
    "sagulung": "Kepulauan Riau",
    "batu ampar": "Kepulauan Riau",
    "sei beduk": "Kepulauan Riau",
    "bulang": "Kepulauan Riau",
    "belakang padang": "Kepulauan Riau",
    # Sumatera Utara
    "medan kota": "Sumatera Utara",
    "medan baru": "Sumatera Utara",
    "medan petisah": "Sumatera Utara",
    "medan sunggal": "Sumatera Utara",
    "medan helvetia": "Sumatera Utara",
    "medan johor": "Sumatera Utara",
    "medan tuntungan": "Sumatera Utara",
    "medan selayang": "Sumatera Utara",
    "medan polonia": "Sumatera Utara",
    "medan maimun": "Sumatera Utara",
    "medan area": "Sumatera Utara",
    "medan denai": "Sumatera Utara",
    "medan tembung": "Sumatera Utara",
    "medan perjuangan": "Sumatera Utara",
    "medan timur": "Sumatera Utara",
    "medan barat": "Sumatera Utara",
    "medan marelan": "Sumatera Utara",
    "medan labuhan": "Sumatera Utara",
    "medan belawan": "Sumatera Utara",
    "medan deli": "Sumatera Utara",
    "medan amplas": "Sumatera Utara",
    # Sulawesi Selatan
    "panakkukang": "Sulawesi Selatan",
    "rappocini": "Sulawesi Selatan",
    "tamalate": "Sulawesi Selatan",
    "mariso": "Sulawesi Selatan",
    "mamajang": "Sulawesi Selatan",
    "makassar kota": "Sulawesi Selatan",
    "ujung pandang": "Sulawesi Selatan",
    "wajo kota": "Sulawesi Selatan",
    "bontoala": "Sulawesi Selatan",
    "tallo": "Sulawesi Selatan",
    "biringkanaya": "Sulawesi Selatan",
    "tamalanrea": "Sulawesi Selatan",
    "manggala": "Sulawesi Selatan",
    "somba opu": "Sulawesi Selatan",
}
for _k, _v in _KECAMATAN_KE_PROVINSI.items():
    if _k not in _KECAMATAN_JABODETABEK:
        _KOTA_KE_PROVINSI.setdefault(_k, _v)

# --------------------------------------------------------------------------- #
# 4. Kota asing yang diketahui -> negara
# --------------------------------------------------------------------------- #
# Dibangun dari lokasi luar negeri yang benar-benar muncul di database (query
# GROUP BY location). Bukan daftar lengkap kota dunia — cukup yang relevan
# untuk sumber-sumber yang dipakai bot ini (LinkedIn/JobSpy, web3career, dan
# lowongan regional Asia Tenggara yang kadang tercampur).
_KOTA_ASING: dict[str, str] = {
    "são paulo": "Brazil", "sao paulo": "Brazil",
    "manila": "Philippines",
    "singapore": "Singapore",
    "bangkok": "Thailand",
    "kuala lumpur": "Malaysia",
    "ho chi minh city": "Vietnam", "hanoi": "Vietnam",
    "new york": "United States", "las vegas": "United States",
    "london": "United Kingdom",
    "cape town": "South Africa",
    "hong kong": "Hong Kong",
    "tokyo": "Japan",
    "sydney": "Australia", "melbourne": "Australia",
    # Kantor Shopee (API ATS-nya memuat lowongan semua negara).
    "shanghai": "China", "shenzhen": "China", "beijing": "China",
    "taipei": "Taiwan", "seoul": "South Korea",
    "mexico city": "Mexico", "ciudad de méxico": "Mexico",
}

_KODE_NEGARA_ASING = {
    "us", "usa", "gb", "uk", "sg", "my", "th", "ph", "vn", "br", "za",
    "jp", "au", "hk", "cn", "in", "ae",
}

# Nama negara lengkap sebagai kata kunci. Ini menangkap kasus seperti
# "Sabah, Malaysia" yang tidak match ke _KOTA_ASING (karena "Sabah" bukan kota
# yang kita kenal) tapi kata "Malaysia"-nya sendiri sudah cukup jadi sinyal.
_NAMA_NEGARA_ASING = {
    "malaysia": "Malaysia", "singapore": "Singapore", "thailand": "Thailand",
    "philippines": "Philippines", "vietnam": "Vietnam", "brazil": "Brazil",
    "united states": "United States", "united kingdom": "United Kingdom",
    "australia": "Australia", "japan": "Japan", "south africa": "South Africa",
    "hong kong": "Hong Kong", "china": "China", "india": "India",
    "united arab emirates": "United Arab Emirates",
    "mexico": "Mexico", "méxico": "Mexico", "south korea": "South Korea",
    "korea": "South Korea", "taiwan": "Taiwan",
}


def _deteksi_negara_asing(location_lower: str) -> str | None:
    for kota, negara in _KOTA_ASING.items():
        if kota in location_lower:
            return negara
    # Nama negara lengkap sebagai kata utuh (\b...\b), bukan substring
    # sembarang — supaya "Indonesia" tidak ikut ke-trigger oleh kebetulan
    # memuat huruf yang sama dengan negara lain.
    for nama, negara in _NAMA_NEGARA_ASING.items():
        if re.search(rf"\b{re.escape(nama)}\b", location_lower):
            return negara
    # Pola "Kota, XX" dengan XX kode negara 2 huruf non-Indonesia,
    # mis. "Jakarta, JW, ID" TIDAK kena ini karena "id" bukan kode asing.
    m = re.search(r",\s*([a-z]{2})\s*$", location_lower)
    if m and m.group(1) in _KODE_NEGARA_ASING:
        return m.group(1).upper()
    return None


# --------------------------------------------------------------------------- #
# Fungsi utama
# --------------------------------------------------------------------------- #
def normalize_location(location: str | None) -> tuple[str | None, str | None]:
    """Ubah lokasi mentah jadi (country, region).

    region cuma terisi kalau country == "Indonesia". Kalau lokasi tidak
    dikenali sama sekali, keduanya None — dianggap "tidak diketahui", bukan
    ditebak paksa.
    """
    if not location or not location.strip():
        return None, None

    raw = location.strip()
    lower = raw.lower()

    # "Kapanewon"/"Kemantren" adalah istilah kecamatan KHUSUS DIY. Dicek
    # duluan supaya "Kapanewon Depok" (Sleman) tidak terbaca sebagai kota
    # Depok di Jawa Barat (jabodetabek).
    if re.match(r"^\s*(kapanewon|kemantren)\b", lower):
        return "Indonesia", "jawa"

    # Kode negara Indonesia polos tanpa embel-embel apa pun.
    if lower in {"id", "idn"}:
        return "Indonesia", None

    # Remote eksplisit disebut sebagai lokasi (bukan work_arrangement) di
    # beberapa sumber lama.
    if lower in {"remote", "wfh", "work from home", "remote, indonesia"}:
        return "Indonesia", "remote"

    # "Indonesia" yang disebut eksplisit di mana pun MENANG atas deteksi
    # negara asing. Tanpa ini, daftar multi-negara seperti
    # "Bangladesh, Indonesia, Vietnam" salah terbaca sebagai Vietnam.
    negara_asing = None if "indonesia" in lower else _deteksi_negara_asing(lower)
    if negara_asing:
        return negara_asing, None

    # Pecah berdasarkan koma, bersihkan tiap segmen, coba cocokkan yang
    # PALING SPESIFIK dulu (segmen pertama biasanya kota/kabupaten/kecamatan).
    segmen_mentah = [s.strip() for s in raw.split(",") if s.strip()]
    segmen_bersih = [_bersihkan_segmen(s) for s in segmen_mentah]

    kandidat = []
    for s in segmen_bersih:
        kandidat.append(s.lower())
        # "DKI-Jakarta" / "Jawa-Barat" (Karir.com) -> "dki jakarta". Versi
        # aslinya tetap dicoba duluan supaya "toli-toli" dsb. tidak rusak.
        if "-" in s:
            kandidat.append(re.sub(r"\s*-\s*", " ", s).lower())

    for kunci in kandidat:

        # 0) Nama wilayah gabungan ditulis langsung (mis. BCA menulis
        #    "Jabodetabek" polos, bukan nama kotanya).
        if kunci in {"jabodetabek", "jabotabek", "jadetabek", "jabodetabekpunjur"}:
            return "Indonesia", "jabodetabek"

        # 1) Kecamatan yang kita tahu persis bagian Jabodetabek — dicek
        #    duluan karena levelnya lebih spesifik dari kota/kabupaten.
        if kunci in _KECAMATAN_JABODETABEK:
            return "Indonesia", "jabodetabek"

        # 2) Kota/kabupaten biasa.
        if kunci in _KOTA_KE_PROVINSI:
            if kunci in _JABODETABEK:
                return "Indonesia", "jabodetabek"
            provinsi = _KOTA_KE_PROVINSI[kunci]
            region = _PROVINSI_KE_REGION.get(provinsi.lower())
            return "Indonesia", region

        # 3) Nama provinsi ditulis langsung tanpa kota (mis. "Bali").
        if kunci in _PROVINSI_LANGSUNG:
            provinsi = _PROVINSI_LANGSUNG[kunci]
            region = _PROVINSI_KE_REGION.get(provinsi.lower())
            if region is None and provinsi.lower() == "dki jakarta":
                region = "jabodetabek"
            return "Indonesia", region

    # "<kota> <arah>" yang tidak ada di kamus, mis. "Denpasar Barat",
    # "Bogor Utara", "Cimahi Selatan": coba nama kotanya saja.
    for kunci in kandidat:
        m = re.match(r"^(.+?)\s+(utara|selatan|timur|barat|tengah|kota|"
                     r"kulon|wetan|kidul|kaler)$", kunci)
        if m and m.group(1) in _KOTA_KE_PROVINSI:
            kota = m.group(1)
            if kota in _JABODETABEK:
                return "Indonesia", "jabodetabek"
            provinsi = _KOTA_KE_PROVINSI[kota]
            return "Indonesia", _PROVINSI_KE_REGION.get(provinsi.lower())

    # Tidak ketemu kota/provinsi spesifik, tapi ada sinyal jelas ini
    # Indonesia (mis. "Indonesia" polos, atau "Jakarta, JW, ID").
    if "indonesia" in lower or re.search(r",\s*id\s*$", lower):
        return "Indonesia", None

    # Frasa penempatan khas lowongan Indonesia tanpa nama kota, mis. BCA
    # "Sesuai Lokasi Tes". Negaranya jelas Indonesia, region-nya tidak.
    if re.search(r"sesuai lokasi|seluruh (wilayah )?(indonesia|cabang)|"
                 r"penempatan (di )?seluruh|nasional|kantor cabang", lower):
        return "Indonesia", None

    # Sama sekali tidak dikenali — jujur mengaku tidak tahu, bukan menebak.
    return None, None
