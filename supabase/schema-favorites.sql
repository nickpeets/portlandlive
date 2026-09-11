-- PortlandLive — Fork Stage 7: account-scoped favorites (user_favorites)
--
-- Run this once, in full, in the Supabase SQL Editor. Depends on Stage 1
-- (profiles).
--
-- PROVENANCE: transcribed from the live catalog of project
-- mhdysfdqoqrohlltgsig, dumped 2026-09-11 (Stage 10 spec, Part 0). Not
-- designed here; copied.
--
-- One row per (user, key). fav_key is the client's opaque string -- the
-- `band::` / `venue::` / show keys the ★ Following filter already uses
-- (index.html, "Account-scoped favorites"). The database does not parse it.
-- Everything is self-scoped: there is no policy that lets anyone read
-- another user's favorites, and no grant to anon at all.

create table if not exists public.user_favorites (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  fav_key text not null,
  created_at timestamptz not null default now(),

  constraint user_favorites_fav_key_length check (
    char_length(fav_key) between 1 and 300
  )
);

create index if not exists user_favorites_user_id_idx
  on public.user_favorites (user_id);

-- Uniqueness is by index, not constraint, in the live catalog.
create unique index if not exists user_favorites_user_key_idx
  on public.user_favorites (user_id, fav_key);

-- Verbatim pg_get_functiondef output from the live catalog (2026-09-11),
-- which is why this block is upper-case and uses $function$ quoting.
CREATE OR REPLACE FUNCTION public.set_favorite_user_id()
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

drop trigger if exists user_favorites_set_user_id on public.user_favorites;

create trigger user_favorites_set_user_id
  before insert on public.user_favorites
  for each row execute function public.set_favorite_user_id();

alter table public.user_favorites enable row level security;

drop policy if exists user_favorites_select_own on public.user_favorites;
drop policy if exists user_favorites_insert_own on public.user_favorites;
drop policy if exists user_favorites_delete_own on public.user_favorites;

create policy user_favorites_select_own
  on public.user_favorites
  for select
  to authenticated
  using (user_id = auth.uid());

create policy user_favorites_insert_own
  on public.user_favorites
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy user_favorites_delete_own
  on public.user_favorites
  for delete
  to authenticated
  using (user_id = auth.uid());

-- No UPDATE: a favorite is added or removed, never edited.

grant select, insert, delete on public.user_favorites to authenticated;
