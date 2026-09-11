-- PortlandLive — Fork Stage 7: account-scoped ticket stubs (user_stubs)
--
-- Run this once, in full, in the Supabase SQL Editor. Depends on Stage 1
-- (profiles).
--
-- PROVENANCE: transcribed from the live catalog of project
-- mhdysfdqoqrohlltgsig, dumped 2026-09-11 (Stage 10 spec, Part 0). Not
-- designed here; copied.
--
-- A stub is a snapshot taken at mint time. Past shows drop out of
-- shows.json, so the shelf renders only from this store, which is why the
-- row carries the show's text fields rather than a slug (index.html, "STUB
-- SHELF"). Every text field defaults to '' and is NOT NULL -- the client
-- sends `s.title || ''` and friends. stub_id mirrors the client's stubIdOf().
-- Self-scoped like user_favorites: no policy reads across users, no anon
-- grant. Stage 10 Part 2's public stub grid needs a new read path.

create table if not exists public.user_stubs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  stub_id text not null,
  title text not null default '',
  venue text not null default '',
  neighborhood text not null default '',
  address text not null default '',
  date text not null default '',
  "time" text not null default '',
  created_at timestamptz not null default now(),

  constraint user_stubs_stub_id_length check (
    char_length(stub_id) between 1 and 400
  ),
  constraint user_stubs_title_length check (char_length(title) <= 200),
  constraint user_stubs_venue_length check (char_length(venue) <= 200),
  constraint user_stubs_neighborhood_length check (char_length(neighborhood) <= 100),
  constraint user_stubs_address_length check (char_length(address) <= 300),
  constraint user_stubs_date_length check (char_length(date) <= 40),
  constraint user_stubs_time_length check (char_length("time") <= 40)
);

create index if not exists user_stubs_user_id_idx
  on public.user_stubs (user_id);

-- Uniqueness is by index, not constraint, in the live catalog.
create unique index if not exists user_stubs_user_stub_idx
  on public.user_stubs (user_id, stub_id);

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.set_stub_user_id()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  new.user_id := auth.uid();
  if new.user_id is null then
    raise exception 'not signed in' using errcode = 'insufficient_privilege';
  end if;
  return new;
end;
$function$;

drop trigger if exists user_stubs_set_user_id on public.user_stubs;

create trigger user_stubs_set_user_id
  before insert on public.user_stubs
  for each row execute function public.set_stub_user_id();

alter table public.user_stubs enable row level security;

drop policy if exists user_stubs_select_own on public.user_stubs;
drop policy if exists user_stubs_insert_own on public.user_stubs;
drop policy if exists user_stubs_delete_own on public.user_stubs;

create policy user_stubs_select_own
  on public.user_stubs
  for select
  to authenticated
  using (user_id = auth.uid());

create policy user_stubs_insert_own
  on public.user_stubs
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy user_stubs_delete_own
  on public.user_stubs
  for delete
  to authenticated
  using (user_id = auth.uid());

-- No UPDATE: a stub is minted or discarded, never edited.

grant select, insert, delete on public.user_stubs to authenticated;
