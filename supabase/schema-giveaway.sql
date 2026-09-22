-- Ticket giveaway (Sep 22 2026). Run once, in full, in the Supabase SQL
-- Editor. Re-running is safe. Depends on schema-signup-refs.sql,
-- schema-show-attendees.sql, schema-reporting.sql (is_moderator).
--
-- Nick and Anita: a pair of tickets to The Brothers Comatose, Aladdin
-- Theater, Sat Oct 31 2026. Entries close Mon Oct 26 at 11:59 PM Pacific.
--   * 1 entry: have an account and tap "I'm going" on any show during the
--     entry window.
--   * +1 per friend who signs up through your invite link
--     (rainorshows.com/?ref=inv-<yourhandle>) AND taps "I'm going" on a
--     show during the window. Sign-up alone doesn't count (stops fakes).
-- Moderators can't win. The draw is weighted random and recorded.

create table if not exists public.giveaways (
  slug text primary key,
  title text not null,
  show_slug text not null,
  prize text not null,
  starts_at timestamptz not null,
  ends_at timestamptz not null,
  winner_id uuid references auth.users (id) on delete set null,
  winner_entries integer,
  drawn_at timestamptz
);
alter table public.giveaways enable row level security;
revoke all on public.giveaways from anon, authenticated;

insert into public.giveaways (slug, title, show_slug, prize, starts_at, ends_at)
values ('brothers-comatose-2026', 'The Brothers Comatose', '2026-10-31-aladdin-theater-the-brothers-comatose',
        'A pair of tickets', now(), timestamptz '2026-10-26 23:59:59 America/Los_Angeles')
on conflict (slug) do nothing;

-- Everyone's entries for one giveaway (definer-only helper).
create or replace function public.giveaway_entries(p_slug text)
returns table (user_id uuid, base integer, invites integer, pending integer, total integer)
language sql security definer set search_path = public stable as $$
  with g as (select * from public.giveaways where slug = p_slug),
  going as (
    select distinct a.user_id from public.show_attendees a, g
     where a.created_at between g.starts_at and g.ends_at
  ),
  inv as (
    select p.id as inviter, r.user_id as invitee,
           (r.user_id in (select user_id from going)) as qualified
      from public.signup_refs r
      join public.profiles p on r.ref = 'inv-' || lower(p.handle)
      , g
     where r.created_at between g.starts_at and g.ends_at
  ),
  people as (select user_id from going union select inviter from inv)
  select pe.user_id,
         (case when pe.user_id in (select user_id from going) then 1 else 0 end) as base,
         (select count(*)::integer from inv where inv.inviter = pe.user_id and inv.qualified) as invites,
         (select count(*)::integer from inv where inv.inviter = pe.user_id and not inv.qualified) as pending,
         (case when pe.user_id in (select user_id from going) then 1 else 0 end)
           + (select count(*)::integer from inv where inv.inviter = pe.user_id and inv.qualified) as total
    from people pe
   where not exists (select 1 from public.moderators m where m.user_id = pe.user_id);
$$;
revoke all on function public.giveaway_entries(text) from public;

-- The open giveaway, for the banner and the page (anyone).
create or replace function public.giveaway_current()
returns table (slug text, title text, show_slug text, prize text, ends_at timestamptz, drawn boolean)
language sql security definer set search_path = public stable as $$
  select g.slug, g.title, g.show_slug, g.prize, g.ends_at, g.winner_id is not null
    from public.giveaways g
   where g.starts_at <= now() and g.ends_at > now() - interval '7 days'
   order by g.ends_at
   limit 1;
$$;
revoke all on function public.giveaway_current() from public;
grant execute on function public.giveaway_current() to anon, authenticated;

-- Your own standing (signed in).
create or replace function public.giveaway_my_status(p_slug text)
returns table (handle text, base integer, invites integer, pending integer, total integer, is_moderator boolean, won boolean)
language sql security definer set search_path = public stable as $$
  select p.handle,
         coalesce(e.base, 0), coalesce(e.invites, 0), coalesce(e.pending, 0), coalesce(e.total, 0),
         exists (select 1 from public.moderators m where m.user_id = auth.uid()),
         exists (select 1 from public.giveaways g where g.slug = p_slug and g.winner_id = auth.uid())
    from public.profiles p
    left join public.giveaway_entries(p_slug) e on e.user_id = p.id
   where p.id = auth.uid();
$$;
revoke all on function public.giveaway_my_status(text) from public;
grant execute on function public.giveaway_my_status(text) to authenticated;

-- How it's going (moderators): entrants and entries.
create or replace function public.giveaway_summary(p_slug text)
returns table (entrants integer, entries integer, invites integer, pending integer)
language plpgsql security definer set search_path = public as $$
begin
  -- A moderator on the site, or you in the SQL Editor (no signed-in user there).
  if auth.uid() is not null and not public.is_moderator() then raise exception 'not a moderator' using errcode = 'insufficient_privilege'; end if;
  return query
    select count(*)::integer, coalesce(sum(e.total), 0)::integer, coalesce(sum(e.invites), 0)::integer, coalesce(sum(e.pending), 0)::integer
      from public.giveaway_entries(p_slug) e where e.total > 0;
end; $$;
revoke all on function public.giveaway_summary(text) from public;
grant execute on function public.giveaway_summary(text) to authenticated;

-- The draw (moderators): weighted random, once. Returns the winner.
create or replace function public.giveaway_draw(p_slug text)
returns table (handle text, display_name text, entries integer, email text)
language plpgsql security definer set search_path = public as $$
declare v_total integer; v_pick integer; v_run integer := 0; r record; v_winner uuid; v_entries integer;
begin
  -- A moderator on the site, or you in the SQL Editor (no signed-in user there).
  if auth.uid() is not null and not public.is_moderator() then raise exception 'not a moderator' using errcode = 'insufficient_privilege'; end if;
  if exists (select 1 from public.giveaways g where g.slug = p_slug and g.winner_id is not null) then
    raise exception 'already drawn' using errcode = 'P0001';
  end if;
  if exists (select 1 from public.giveaways g where g.slug = p_slug and g.ends_at > now()) then
    raise exception 'entries are still open' using errcode = 'P0001';
  end if;
  select coalesce(sum(e.total), 0) into v_total from public.giveaway_entries(p_slug) e where e.total > 0;
  if v_total = 0 then raise exception 'no entries' using errcode = 'P0001'; end if;
  v_pick := 1 + floor(random() * v_total)::integer;
  for r in select e.user_id, e.total from public.giveaway_entries(p_slug) e where e.total > 0 order by e.user_id loop
    v_run := v_run + r.total;
    if v_run >= v_pick then v_winner := r.user_id; v_entries := r.total; exit; end if;
  end loop;
  update public.giveaways set winner_id = v_winner, winner_entries = v_entries, drawn_at = now() where slug = p_slug;
  return query
    select p.handle, p.display_name, v_entries, u.email::text
      from public.profiles p join auth.users u on u.id = p.id where p.id = v_winner;
end; $$;
revoke all on function public.giveaway_draw(text) from public;
grant execute on function public.giveaway_draw(text) to authenticated;

select slug, title, prize, ends_at from public.giveaways;
