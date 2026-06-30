-- ============================================================
-- Supabase setup for Design Inspiration Library
-- Run this in the Supabase SQL Editor (one time).
-- Model: PUBLIC READ, OWNER-ONLY WRITE.
--   - Reads (gallery) use the publishable/anon key.
--   - Writes (upload script + Chrome plugin) use the service_role
--     key, which bypasses RLS. No public insert policy exists,
--     so the publishable key cannot write.
-- ============================================================

create table if not exists inspirations (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  description text,
  source_url text,
  image_path text not null,        -- path inside the storage bucket
  section text default 'Other References',
  created_at timestamptz default now()
);

-- Public storage bucket for the images
insert into storage.buckets (id, name, public)
values ('inspirations', 'inspirations', true)
on conflict (id) do nothing;

-- Enable RLS on the table
alter table inspirations enable row level security;

-- Anyone can READ rows
create policy "public read inspirations"
  on inspirations for select using (true);

-- Anyone can READ images from the bucket
create policy "public read images"
  on storage.objects for select using (bucket_id = 'inspirations');

-- NOTE: intentionally NO insert/update/delete policies.
-- Only the service_role key (held by you) can write.

-- ============================================================
-- Project URL:  https://hxxcwswrwgftolfbuosf.supabase.co
-- Publishable key (safe, public, READ-only in practice):
--   sb_publishable_GJkQX8HfXOOcyQgLHYF0Fg_TDAadrX1
-- Service role key: DO NOT paste anywhere public. Get it from
--   Supabase > Project Settings > API > service_role (secret).
--   Put it in a local .env as SUPABASE_SERVICE_KEY for uploads.
-- ============================================================
