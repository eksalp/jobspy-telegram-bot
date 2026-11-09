# Menambahkan filter Negara & Region untuk Jobly

Tiga langkah, urutannya penting.

## 1. Migrasi database (sekali saja)

Buka Supabase → SQL Editor, jalankan isi `migration_add_region.sql`.
Ini menambah dua kolom baru ke tabel `jobs`:

- `country` — nama negara, mis. "Indonesia", "Brazil", atau NULL kalau tidak
  diketahui
- `region` — HANYA terisi kalau country = "Indonesia". Nilainya salah satu
  dari: `jabodetabek`, `jawa`, `sumatera`, `kalimantan`, `sulawesi`,
  `bali_nusra`, `indonesia_timur`, `remote`, atau NULL

## 2. Isi data yang sudah ada (sekali saja)

```bash
cd ~/Downloads/Project/jobspy-telegram-bot
cp /path/ke/location_normalizer.py .
cp /path/ke/backfill_location.py .

# Lihat dulu hasilnya TANPA mengubah database:
python backfill_location.py --dry-run

# Kalau hasilnya masuk akal, jalankan sungguhan:
python backfill_location.py
```

Baca laporan "TIDAK DIKENALI" di outputnya — itu daftar variasi teks lokasi
yang belum ada di kamus `location_normalizer.py`. Kalau ada yang seharusnya
dikenali (misalnya kota yang belum masuk daftar), tambahkan ke
`_KOTA_KE_PROVINSI` atau `_KOTA_ASING` di file itu, lalu jalankan ulang
`backfill_location.py` — aman diulang berkali-kali, tidak akan menduplikasi.

## 3. Sambungkan ke scraper (sekali saja, untuk data BARU)

```bash
python pasang_normalisasi_lokasi.py
```

Ini menambal `sites/base.py` supaya setiap lowongan baru dari 23 adapter
otomatis dapat `country`+`region` saat scraping — kamu tidak perlu mengubah
satu pun file adapter. Cadangan otomatis dibuat di `sites/base.py.bak`.

## Query yang bisa dipakai Jobly setelah ini

```sql
-- Semua lowongan Indonesia
select * from jobs where country = 'Indonesia';

-- Lowongan Jabodetabek saja
select * from jobs where region = 'jabodetabek';

-- Lowongan remote
select * from jobs where region = 'remote';

-- Daftar negara untuk dropdown filter (selain Indonesia)
select country, count(*) from jobs
where country is not null and country != 'Indonesia'
group by country order by count(*) desc;
```

## Kalau nanti ada kota yang tidak dikenali kamus

`location_normalizer.py` sengaja mengembalikan `(None, None)` untuk lokasi
yang tidak dikenali, bukan menebak — supaya tidak ada kota yang salah masuk
region. Untuk memperbaikinya:

1. Jalankan `python backfill_location.py --dry-run` untuk melihat daftar
   lokasi yang belum dikenali beserta jumlah barisnya.
2. Tambahkan kota/kabupaten yang sering muncul ke `_KOTA_KE_PROVINSI` di
   `location_normalizer.py` (format: `"nama kota lowercase": "Nama Provinsi"`).
3. Jalankan ulang `python backfill_location.py` (bukan --dry-run) untuk
   menerapkannya ke data yang sudah ada.

Data baru otomatis ikut memakai kamus yang sudah diperbarui, karena
`sites/base.py` memanggil `normalize_location()` yang sama setiap kali.
