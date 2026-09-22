-- PortlandLive -- People you may know (Sep 22 2026).
--
-- WHY: people pick names that aren't their own, so @-search only finds
-- someone whose handle you already know. Suggestions go by what people do:
--   1. mutual follows -- people followed (accepted) by people you follow.
--      Following lists are already readable by any signed-in person.
--   2. same shows -- people in Who's Going on shows you marked going.
--      People set to "No one" (upcoming_visibility = 'private') are left out.
-- The card says why only as "Followed by X" or "At N of your shows".
-- Off switches (bookmark menu): suggest_me = false -> never suggested;
-- show_card = false -> no card in your feed. The x hides one person for good.
-- Fallback (Sep 22 2026): members who joined in the last 30 days fill the
-- leftover slots, labeled "New on Rain Or Shows".
-- Depends on schema-follow-requests.sql and schema-profile-pages.sql.
-- Run once, in full, in the Supabase SQL Editor. Re-running is safe.

create table if not exists public.pymk_prefs (
  user_id uuid primary key references auth.users (id) on delete cascade,
  suggest_me boolean not null default true,
  show_card  boolean not null default true,
  updated_at timestamptz not null default now()
);
alter table public.pymk_prefs enable row level security;
revoke all on public.pymk_prefs from anon, authenticated;

create table if not exists public.pymk_hidden (
  user_id   uuid not null references auth.users (id) on delete cascade,
  hidden_id uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (user_id, hidden_id)
);
alter table public.pymk_hidden enable row level security;
revoke all on public.pymk_hidden from anon, authenticated;

create or replace function public.people_you_may_know(p_limit integer default 12)
returns table (id uuid, handle text, display_name text, avatar_url text,
               mutuals integer, mutual_names text[], shared_shows integer)
language plpgsql
security definer
set search_path = public
as $$
declare v_me uuid := auth.uid();
begin
  if v_me is null then return; end if;
  if exists (select 1 from public.pymk_prefs x where x.user_id = v_me and not x.show_card) then return; end if;
  if not public.rate_limit_take('people_you_may_know', 30) then
    raise exception 'rate_limited' using errcode = 'P0001';
  end if;
  return query
  with fof as (
    select f2.followee_id as cand,
           count(distinct f1.followee_id)::integer as n,
           (array_agg(coalesce(nullif(pm.display_name, ''), pm.handle) order by f1.created_at desc))[1:2] as names
      from public.follows f1
      join public.follows f2 on f2.follower_id = f1.followee_id and f2.status = 'accepted'
      join public.profiles pm on pm.id = f1.followee_id
     where f1.follower_id = v_me and f1.status = 'accepted'
     group by f2.followee_id
  ), shared as (
    select a2.user_id as cand, count(distinct a2.show_slug)::integer as n
      from public.show_attendees a1
      join public.show_attendees a2 on a2.show_slug = a1.show_slug and a2.user_id <> a1.user_id
      join public.profiles pv on pv.id = a2.user_id and pv.upcoming_visibility <> 'private'
     where a1.user_id = v_me
     group by a2.user_id
  ), linked as (
    select coalesce(fof.cand, shared.cand) as cand,
           coalesce(fof.n, 0) as m, coalesce(fof.names, '{}'::text[]) as names,
           coalesce(shared.n, 0) as s
      from fof full join shared on shared.cand = fof.cand
  ), c as (
    -- Newest-members fallback (Sep 22 2026): people who joined in the last
    -- 30 days fill whatever slots the two real signals leave. They sort
    -- after every linked person (score 0) and show as "New on Rain Or
    -- Shows" on the card (mutuals = 0 and shared_shows = 0).
    select * from linked
    union all
    select np.id, 0, '{}'::text[], 0
      from public.profiles np
     where np.created_at > now() - interval '30 days'
       and not exists (select 1 from linked l where l.cand = np.id)
  )
  select p.id, p.handle, p.display_name, p.avatar_url, c.m, c.names, c.s
    from c
    join public.profiles p on p.id = c.cand
   where c.cand <> v_me
     and p.handle is not null
     and not exists (select 1 from public.follows f where f.follower_id = v_me and f.followee_id = c.cand)
     and not exists (select 1 from public.pymk_hidden h where h.user_id = v_me and h.hidden_id = c.cand)
     and not exists (select 1 from public.pymk_prefs x where x.user_id = c.cand and not x.suggest_me)
   order by (c.m * 3 + c.s * 2) desc, c.m desc, p.created_at desc, lower(p.handle)
   limit greatest(1, least(coalesce(p_limit, 12), 25));
end;
$$;
revoke all on function public.people_you_may_know(integer) from public;
grant execute on function public.people_you_may_know(integer) to authenticated;

create or replace function public.pymk_hide(p_other uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('pymk_hide', 60) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  insert into public.pymk_hidden (user_id, hidden_id) values (auth.uid(), p_other)
  on conflict do nothing;
  return true;
end;
$$;
revoke all on function public.pymk_hide(uuid) from public;
grant execute on function public.pymk_hide(uuid) to authenticated;

create or replace function public.pymk_prefs_get()
returns table (suggest_me boolean, show_card boolean)
language sql
security definer
set search_path = public
stable
as $$
  select coalesce((select x.suggest_me from public.pymk_prefs x where x.user_id = auth.uid()), true),
         coalesce((select x.show_card  from public.pymk_prefs x where x.user_id = auth.uid()), true)
   where auth.uid() is not null;
$$;
revoke all on function public.pymk_prefs_get() from public;
grant execute on function public.pymk_prefs_get() to authenticated;

create or replace function public.pymk_prefs_set(p_suggest_me boolean default null, p_show_card boolean default null)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  insert into public.pymk_prefs (user_id, suggest_me, show_card)
  values (auth.uid(), coalesce(p_suggest_me, true), coalesce(p_show_card, true))
  on conflict (user_id) do update
     set suggest_me = coalesce(p_suggest_me, public.pymk_prefs.suggest_me),
         show_card  = coalesce(p_show_card,  public.pymk_prefs.show_card),
         updated_at = now();
  return true;
end;
$$;
revoke all on function public.pymk_prefs_set(boolean, boolean) from public;
grant execute on function public.pymk_prefs_set(boolean, boolean) to authenticated;

select proname from pg_proc
 where proname in ('people_you_may_know', 'pymk_hide', 'pymk_prefs_get', 'pymk_prefs_set')
 order by proname;
