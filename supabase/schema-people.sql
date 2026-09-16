-- PortlandLive -- People (Sep 2026): follower / following lists and handle
-- search. Run once, in full, in the Supabase SQL Editor. Depends on
-- schema-follows.sql and schema-profile-pages.sql (rate_limit_take).
--
-- Reverses the "no lists" decision in schema-follows.sql on Nick's call:
-- "how do people find other people now?" -- they could not, except at a
-- show. The one line kept from that decision: these are for signed-in
-- people. Counts stay public; names behind them do not go to anonymous
-- callers, and handle search is not a scraping surface for logged-out
-- visitors. Every call is rate-limited.
--
-- Re-running: safe.

-- Who follows p_target, newest first.
create or replace function public.followers_of(p_target uuid, p_limit integer default 100)
returns table (id uuid, handle text, display_name text, avatar_url text, since timestamptz)
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('followers_of', 60) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  return query
    select p.id, p.handle, p.display_name, p.avatar_url, f.created_at
      from public.follows f
      join public.profiles p on p.id = f.follower_id
     where f.followee_id = p_target
     order by f.created_at desc
     limit greatest(1, least(coalesce(p_limit, 100), 500));
end;
$$;
revoke all on function public.followers_of(uuid, integer) from public;
grant execute on function public.followers_of(uuid, integer) to authenticated;

-- Who p_target follows, newest first.
create or replace function public.following_of(p_target uuid, p_limit integer default 100)
returns table (id uuid, handle text, display_name text, avatar_url text, since timestamptz)
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('following_of', 60) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  return query
    select p.id, p.handle, p.display_name, p.avatar_url, f.created_at
      from public.follows f
      join public.profiles p on p.id = f.followee_id
     where f.follower_id = p_target
     order by f.created_at desc
     limit greatest(1, least(coalesce(p_limit, 100), 500));
end;
$$;
revoke all on function public.following_of(uuid, integer) from public;
grant execute on function public.following_of(uuid, integer) to authenticated;

-- Handle / name search. Prefix on handle, substring on display name; handle
-- prefix hits first. "@" is stripped so "@nick" and "nick" behave the same.
create or replace function public.search_profiles(p_q text, p_limit integer default 10)
returns table (id uuid, handle text, display_name text, avatar_url text)
language plpgsql
security definer
set search_path = public
as $$
declare v_q text;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('search_profiles', 120) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  v_q := lower(trim(both from regexp_replace(coalesce(p_q, ''), '^@', '')));
  if length(v_q) < 2 then return; end if;
  return query
    select p.id, p.handle, p.display_name, p.avatar_url
      from public.profiles p
     where p.handle is not null
       and (lower(p.handle) like v_q || '%' or lower(coalesce(p.display_name, '')) like '%' || v_q || '%')
     order by (lower(p.handle) like v_q || '%') desc, lower(p.handle)
     limit greatest(1, least(coalesce(p_limit, 10), 25));
end;
$$;
revoke all on function public.search_profiles(text, integer) from public;
grant execute on function public.search_profiles(text, integer) to authenticated;
