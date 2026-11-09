-- Jalankan script ini di Supabase SQL Editor (Project > SQL Editor > New query)
-- sebelum menjalankan bot untuk pertama kali.

create table if not exists jobs (
    id                     bigserial primary key,
    job_id                 text,               -- id job dari situs asal (kolom "id" jobspy)
    site                   text,               -- indeed / linkedin / glassdoor / google / ziprecruiter / bayt / naukri
    job_url                text,
    job_url_direct         text,
    title                  text,
    company                text,
    location               text,
    date_posted            date,
    job_type               text,
    salary_source          text,
    interval               text,
    min_amount             numeric,
    max_amount             numeric,
    currency               text,
    is_remote              boolean,
    job_level              text,
    job_function           text,
    listing_type           text,
    emails                 text,
    description            text,
    company_industry       text,
    company_url            text,
    company_logo           text,
    company_url_direct     text,
    company_addresses      text,
    company_num_employees  text,
    company_revenue        text,
    company_description    text,
    skills                 text,
    experience_range       text,
    company_rating         numeric,
    company_reviews_count  integer,
    vacancy_count          integer,
    work_from_home_type    text,

    -- metadata pencarian, berguna untuk lihat riwayat /update
    search_term            text,
    search_location        text,
    requested_by_chat_id   text,

    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now(),

    -- kombinasi site + job_id dipakai sebagai kunci dedup saat upsert.
    -- job_url dipakai sebagai fallback kalau job_id kosong (mis. Google jobs).
    constraint jobs_site_job_id_key unique (site, job_id)
);

create index if not exists jobs_site_idx on jobs (site);
create index if not exists jobs_date_posted_idx on jobs (date_posted desc);
create index if not exists jobs_search_term_idx on jobs (search_term);

-- trigger kecil supaya updated_at otomatis ter-update tiap kali row di-upsert/diubah
create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists jobs_set_updated_at on jobs;
create trigger jobs_set_updated_at
before update on jobs
for each row execute function set_updated_at();
