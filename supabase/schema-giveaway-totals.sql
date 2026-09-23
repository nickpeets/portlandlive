-- Public entry counter for the giveaway page (Sep 22 2026, Nick). Run once in
-- the Supabase SQL Editor; re-running is safe. Depends on schema-giveaway.sql.
-- Totals only -- how many people and entries -- never who.
create or replace function public.giveaway_totals(p_slug text)
returns table (entrants integer, entries integer)
language sql security definer set search_path = public stable as $$
  select count(*)::integer, coalesce(sum(e.total), 0)::integer
    from public.giveaway_entries(p_slug) e
   where e.total > 0;
$$;
revoke all on function public.giveaway_totals(text) from public;
grant execute on function public.giveaway_totals(text) to anon, authenticated;

select * from public.giveaway_totals('brothers-comatose-2026');
