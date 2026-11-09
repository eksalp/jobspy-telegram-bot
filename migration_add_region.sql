-- Migrasi: tambah kolom country & region ke tabel jobs.
--
-- Jalankan ini SEKALI lewat Supabase SQL Editor sebelum menjalankan
-- backfill_location.py. Aman dijalankan berulang (pakai IF NOT EXISTS).
--
-- region cuma terisi kalau country = 'Indonesia'. Untuk negara lain,
-- region selalu NULL — Jobly cukup filter country untuk lowongan luar
-- negeri, tidak perlu breakdown wilayah untuk itu.

alter table jobs
    add column if not exists country text,
    add column if not exists region text;

-- Index untuk mempercepat filter di Jobly (WHERE country = ... AND region = ...)
create index if not exists idx_jobs_country on jobs (country);
create index if not exists idx_jobs_region on jobs (region);

-- Batasan nilai region supaya tidak ada typo yang lolos di masa depan.
-- DROP dulu kalau sudah pernah ada dari percobaan sebelumnya, baru buat ulang.
alter table jobs drop constraint if exists jobs_region_check;
alter table jobs
    add constraint jobs_region_check
    check (region is null or region in (
        'jabodetabek', 'jawa', 'sumatera', 'kalimantan',
        'sulawesi', 'bali_nusra', 'indonesia_timur', 'remote'
    ));
