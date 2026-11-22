-- Giveaway #2: Dogs In A Pile, Revolution Hall, Sat Jan 9 2027 (Nov 22 2026).
-- Run once, in full, in the Supabase SQL Editor. Re-running is safe. Depends
-- on schema-giveaway.sql, schema-giveaway-totals.sql, schema-photo-likes.sql.
--
-- Entries open Mon Nov 30 2026 and close Sun Jan 3 2027 at 11:59 PM Pacific.
--   * 1 entry: tap "I'm going" on any show during the window.
--   * +1 per friend who joins through your invite link and taps "I'm going".
--   * +1 per show you post a photo or clip from.
--   * NEW: +1 for tapping "I'm going" on the giveaway show itself.
-- giveaway_totals, _summary and _draw read e.total, so they pick up the new
-- column unchanged. The banner and page appear on their own on Nov 30
-- (giveaway_current only returns a giveaway whose starts_at has passed).

insert into public.giveaways (slug, title, show_slug, prize, starts_at, ends_at)
values ('dogs-in-a-pile-2027', 'Dogs In A Pile', '2027-01-09-revolution-hall-dogs-in-a-pile',
        'A pair of tickets',
        timestamptz '2026-11-30 06:00:00 America/Los_Angeles',
        timestamptz '2027-01-03 23:59:59 America/Los_Angeles')
on conflict (slug) do nothing;

-- Same shape as schema-photo-likes.sql plus a showgoing column.
drop function if exists public.giveaway_my_status(text);
drop function if exists public.giveaway_entries(text);
create or replace function public.giveaway_entries(p_slug text)
returns table (user_id uuid, base integer, invites integer, pending integer, photos integer, showgoing integer, total integer)
language sql security definer set search_path = public stable as $$
  with g as (select * from public.giveaways where slug = p_slug),
  going as (
    select distinct a.user_id from public.show_attendees a, g
     where a.created_at between g.starts_at and g.ends_at
  ),
  -- "I'm going" on the giveaway's own show, whenever it was tapped (a tap
  -- before the window still means they're going).
  thisshow as (
    select distinct a.user_id from public.show_attendees a, g
     where a.show_slug = g.show_slug and a.created_at <= g.ends_at
  ),
  inv as (
    select p.id as inviter, r.user_id as invitee,
           (r.user_id in (select user_id from going)) as qualified
      from public.signup_refs r
      join public.profiles p on r.ref = 'inv-' || lower(p.handle)
      , g
     where r.created_at between g.starts_at and g.ends_at
  ),
  pics as (
    select ph.user_id, count(distinct ph.show_slug)::integer as n
      from public.show_photos ph, g
     where ph.created_at between g.starts_at and g.ends_at
       and not exists (select 1 from public.content_reports r where r.target_type = 'photo'
                        and r.target_id = ph.id and (r.status is null or r.status = 'upheld'))
     group by ph.user_id
  ),
  people as (select user_id from going union select inviter from inv union select user_id from pics union select user_id from thisshow)
  select pe.user_id,
         (case when pe.user_id in (select user_id from going) then 1 else 0 end) as base,
         (select count(*)::integer from inv where inv.inviter = pe.user_id and inv.qualified) as invites,
         (select count(*)::integer from inv where inv.inviter = pe.user_id and not inv.qualified) as pending,
         coalesce((select pics.n from pics where pics.user_id = pe.user_id), 0) as photos,
         (case when pe.user_id in (select user_id from thisshow) then 1 else 0 end) as showgoing,
         (case when pe.user_id in (select user_id from going) then 1 else 0 end)
           + (select count(*)::integer from inv where inv.inviter = pe.user_id and inv.qualified)
           + coalesce((select pics.n from pics where pics.user_id = pe.user_id), 0)
           + (case when pe.user_id in (select user_id from thisshow) then 1 else 0 end) as total
    from people pe
   where not exists (select 1 from public.moderators m where m.user_id = pe.user_id);
$$;
revoke all on function public.giveaway_entries(text) from public;

create or replace function public.giveaway_my_status(p_slug text)
returns table (handle text, base integer, invites integer, pending integer, photos integer, showgoing integer, total integer, is_moderator boolean, won boolean)
language sql security definer set search_path = public stable as $$
  select p.handle,
         coalesce(e.base, 0), coalesce(e.invites, 0), coalesce(e.pending, 0), coalesce(e.photos, 0), coalesce(e.showgoing, 0), coalesce(e.total, 0),
         exists (select 1 from public.moderators m where m.user_id = auth.uid()),
         exists (select 1 from public.giveaways g where g.slug = p_slug and g.winner_id = auth.uid())
    from public.profiles p
    left join public.giveaway_entries(p_slug) e on e.user_id = p.id
   where p.id = auth.uid();
$$;
revoke all on function public.giveaway_my_status(text) from public;
grant execute on function public.giveaway_my_status(text) to authenticated;

-- Check: the row is there and the window is right (Pacific).
select slug, title, show_slug,
       starts_at at time zone 'America/Los_Angeles' as opens_pt,
       ends_at   at time zone 'America/Los_Angeles' as closes_pt
  from public.giveaways order by starts_at;
select * from public.giveaway_totals('dogs-in-a-pile-2027');
