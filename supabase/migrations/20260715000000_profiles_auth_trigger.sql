-- SAFE FOR DWELLSENSE (reviewed):
-- - Does NOT drop/alter crime_reports, reports_311, building_permits, eviction_records, adsb_samples
-- - Only creates/updates public.profiles + one auth.users trigger/function named below
-- - DROP ... IF EXISTS only removes our own policies/trigger if recreating them
--
-- Purpose: fix "Database error saving new user" on Google signup, and prepare AuthUser.id for Saved Reports.

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text,
  created_at timestamptz not null default now()
);

-- If an older incomplete profiles table already exists, add missing columns (no-op if present).
alter table public.profiles add column if not exists email text;
alter table public.profiles add column if not exists created_at timestamptz default now();

alter table public.profiles enable row level security;

drop policy if exists "Users can read own profile" on public.profiles;
create policy "Users can read own profile"
  on public.profiles for select
  using ((select auth.uid()) = id);

drop policy if exists "Users can update own profile" on public.profiles;
create policy "Users can update own profile"
  on public.profiles for update
  using ((select auth.uid()) = id);

-- security definer + empty search_path = Supabase-recommended pattern for auth triggers
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do update
    set email = excluded.email;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row
  execute function public.handle_new_user();

-- Auth inserts as supabase_auth_admin; authenticated users can read/update their row.
grant usage on schema public to supabase_auth_admin;
grant insert, update on table public.profiles to supabase_auth_admin;
grant select, update on table public.profiles to authenticated;
grant all on table public.profiles to service_role;
