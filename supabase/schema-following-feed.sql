-- PortlandLive — Fork Stage 10, Part 5: the unified Following feed (D2)
--
-- Run this once, in full, in the Supabase SQL Editor, BEFORE deploying the
-- matching index.html. Depends on schema-follows.sql (follows, i_follow,
-- can_see_upcoming) and schema-show-attendees.sql.
--
-- D2 (decided): "Following" means bands, venues AND people. One pill, one
-- feed, one question -- shows involving anything I follow. The band and
-- venue halves are local data (user_favorites keys already in memory). This
-- file is the people half: for the shows currently in the feed, which of
-- the people I follow are going.
--
-- Shape: attendance_for_user (Part 2) for one person, widened to everyone
-- the caller follows, and bounded the same way -- the caller sends the
-- feed's current slugs and gets the intersection, so nothing about shows
-- outside the feed is returned. Visibility goes through can_see_upcoming,
-- the single gate: a followers-only person contributes rows only to their
-- followers, and since this query is BY DEFINITION over people the caller
-- follows, that gate is satisfied for every row today. It is still called,
-- so that whatever is added to the gate later (blocking, say) applies here
-- without a second edit.
--
-- The handle, name and avatar of each person come back so the reason line
-- can say "@handle going" with a face. Scoped to people the caller already
-- follows -- who were followed from their own profile page, handle showing.
-- Not a general id -> handle mapper (D3).
--
-- Dedupe is the client's job and is done by iterating the canonical show
-- list once, not by unioning two result sets -- see index.html.
--
-- Re-running: safe.

create or replace function public.followed_attendance(p_slugs text[])
returns table (
  show_slug text, user_id uuid, handle text, display_name text,
  avatar_url text, created_at timestamptz
)
language sql
security definer
set search_path = public
stable
as $$
  select a.show_slug, a.user_id, p.handle, p.display_name, p.avatar_url, a.created_at
    from public.follows f
    join public.show_attendees a on a.user_id = f.followee_id
    join public.profiles p on p.id = a.user_id
   where f.follower_id = auth.uid()
     and a.show_slug = any (coalesce(p_slugs, '{}'::text[]))
     and public.can_see_upcoming(a.user_id)
   order by a.show_slug, a.created_at;
$$;

revoke all on function public.followed_attendance(text[]) from public;
grant execute on function public.followed_attendance(text[]) to authenticated;
