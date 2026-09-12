-- PortlandLive — Fork Stage 10, Part 3.5: names link to profiles
--
-- Run this once, in full, in the Supabase SQL Editor, BEFORE deploying the
-- matching index.html. Depends on schema-profile-pages.sql
-- (attendees_for_show) and schema-handles.sql (profiles.handle).
--
-- After Part 3 the only clickable names on the site were hand-typed
-- @mentions. Comment authors and Who's Going attendees were plain text.
-- This gives the client their handles so those names can link to
-- #/u/<handle> -- and only theirs.
--
-- The shape matters (D3): profiles.handle is selectable by no client role
-- because anon can already list every profile id, so a general
-- "ids -> handles" function would be the bulk enumeration D3 exists to
-- prevent. Both reads here are keyed on something the caller already holds
-- -- a show slug, a list of comment ids -- and return handles only for
-- people who chose to act in public there (marked going, posted). Same
-- pattern as mentions_for_comments (Part 3).
--
--   attendees_for_show(slug)         gains a handle column. Folded in rather
--                                    than a second function: one round trip,
--                                    roster and handles can never disagree,
--                                    and the scope is identical. A return-type
--                                    change needs DROP + CREATE; the client
--                                    ignores the extra column until it
--                                    deploys and uses it after.
--   authors_for_comments(uuid[])     comment_id, user_id, handle for the
--                                    authors of THESE comments.
--
-- Re-running: safe.

-- ---------------------------------------------------------------------------
-- 1. attendees_for_show, now with handle
-- ---------------------------------------------------------------------------
drop function if exists public.attendees_for_show(text);

create function public.attendees_for_show(p_show_slug text)
returns table (id uuid, user_id uuid, display_name text, handle text, created_at timestamptz)
language sql
security definer
set search_path = public
stable
as $$
  select a.id, a.user_id, a.display_name, p.handle, a.created_at
    from public.show_attendees a
    left join public.profiles p on p.id = a.user_id
   where a.show_slug = p_show_slug
   order by a.created_at;
$$;

revoke all on function public.attendees_for_show(text) from public;
grant execute on function public.attendees_for_show(text) to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2. Comment authors
-- ---------------------------------------------------------------------------
create or replace function public.authors_for_comments(p_comment_ids uuid[])
returns table (comment_id uuid, user_id uuid, handle text)
language sql
security definer
set search_path = public
stable
as $$
  select c.id, c.user_id, p.handle
    from public.comments c
    join public.profiles p on p.id = c.user_id
   where c.id = any (coalesce(p_comment_ids, '{}'::uuid[]));
$$;

revoke all on function public.authors_for_comments(uuid[]) from public;
grant execute on function public.authors_for_comments(uuid[]) to anon, authenticated;

-- Not done here, on purpose: inbox rows (the other party's name) and ticket
-- post bylines are still plain text. Each needs its own scoped resolver
-- (thread ids -> participants; post ids -> posters) and, for the inbox, a
-- row that is currently one <button> and cannot contain a link. Neither is
-- free; both are noted for a later part.
