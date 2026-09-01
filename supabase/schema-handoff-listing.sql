-- PortlandLive — handoff-aware listing: per-post handed-off counts
--
-- Run this once, in full, in the Supabase SQL Editor. Depends on Stage 3
-- (ticket_posts), Stage 4 (ticket_threads) and Stage 5 (handed_off_at).
--
-- Stage 5 already ships handoff_count / handoff_counts, which answer "how many
-- handoffs has this PERSON completed" -- a credibility signal attached to a
-- poster. This answers a different question: "how many of THIS POST's spares
-- have been handed off", which is what decides whether the post still belongs
-- in the listing.
--
-- Same shape and the same reason as the existing functions: ticket_threads is
-- invisible to anon and, for authenticated users, readable only for threads
-- they participate in -- so nobody can compute this by querying the table.
-- This function is the only way to ask, and it answers with a bare integer per
-- post id: no thread ids, no requester identities, no timestamps.
--
-- Public because what it describes is public: ticket_posts are readable logged
-- out, so whether a post is still open has to be too, or a logged-out visitor
-- sees spares that are already gone.
--
-- unnest(post_ids) drives the join, so a post with no threads at all comes
-- back as 0 rather than being omitted -- the caller never has to distinguish
-- "zero handed off" from "missing from the result".
create or replace function public.handoff_counts_for_posts(post_ids uuid[])
returns table (ticket_post_id uuid, handed_off integer)
language sql
security definer
set search_path = public
stable
as $$
  select p.id,
         (count(t.id) filter (where t.handed_off_at is not null))::int
    from unnest(post_ids) as p(id)
    left join public.ticket_threads t on t.ticket_post_id = p.id
   group by p.id;
$$;

revoke all on function public.handoff_counts_for_posts(uuid[]) from public;
grant execute on function public.handoff_counts_for_posts(uuid[]) to anon, authenticated;
