-- Picks (Sep 22 2026). Run once, in full, in the Supabase SQL Editor.
-- Re-running is safe. Depends on schema-reporting.sql (is_moderator) and
-- schema-favorites.sql (user_favorites).
--
-- The nightly build marks Picks candidates (big room, in town, next 14 days,
-- carries our Ticketmaster or Vivid link) and gives each a buzz score. The
-- page ranks them with the heart counts below and applies moderator pins:
--   'in'  -- always in Picks while the show is upcoming
--   'out' -- never in Picks, however it ranks
-- Pins are set from the Picks feed and show pages, moderators only.

create table if not exists public.pick_pins (
  slug text primary key check (char_length(slug) between 1 and 200),
  state text not null check (state in ('in', 'out')),
  set_by uuid references auth.users (id) on delete set null,
  set_at timestamptz not null default now()
);
alter table public.pick_pins enable row level security;
revoke all on public.pick_pins from anon, authenticated;

-- Everyone reads the pins: they decide what Picks shows.
create or replace function public.pick_pins_all()
returns table (slug text, state text)
language sql security definer set search_path = public stable as $$
  select slug, state from public.pick_pins;
$$;
revoke all on function public.pick_pins_all() from public;
grant execute on function public.pick_pins_all() to anon, authenticated;

-- Moderators set or clear a pin. p_state null clears it.
create or replace function public.pick_pin_set(p_slug text, p_state text)
returns boolean
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_moderator() then raise exception 'not a moderator' using errcode = 'insufficient_privilege'; end if;
  if p_state is null then
    delete from public.pick_pins where slug = p_slug;
  elsif p_state in ('in', 'out') then
    insert into public.pick_pins (slug, state, set_by) values (p_slug, p_state, auth.uid())
    on conflict (slug) do update set state = excluded.state, set_by = excluded.set_by, set_at = now();
  else
    raise exception 'bad state' using errcode = 'P0001';
  end if;
  return true;
end; $$;
revoke all on function public.pick_pin_set(text, text) from public;
grant execute on function public.pick_pin_set(text, text) to authenticated;

-- How many people hearted each of these shows. Counts only -- never who.
create or replace function public.pick_hearts(p_keys text[])
returns table (fav_key text, n integer)
language sql security definer set search_path = public stable as $$
  select f.fav_key, count(*)::integer
    from public.user_favorites f
   where f.fav_key = any (coalesce(p_keys, '{}'::text[]))
   group by f.fav_key;
$$;
revoke all on function public.pick_hearts(text[]) from public;
grant execute on function public.pick_hearts(text[]) to anon, authenticated;

-- Check: the three functions exist.
select proname from pg_proc where proname in ('pick_pins_all', 'pick_pin_set', 'pick_hearts') order by proname;
