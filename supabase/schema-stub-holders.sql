-- Who has the stub for a show (Sep 20 2026): the "Was There" list on past
-- show pages. Keyed by the stub id (title|venue|date, the same key the page
-- mints with). Respects each holder's visibility the way their profile does
-- (can_see_upcoming: public, or followers, or "no one"), so a private
-- person never appears. Run once in the Supabase SQL Editor.
create or replace function public.stub_holders(p_stub_id text)
returns table (user_id uuid, display_name text, handle text, created_at timestamptz)
language sql security definer set search_path = public stable as $$
  select s.user_id, p.display_name, p.handle, s.created_at
    from public.user_stubs s
    join public.profiles p on p.id = s.user_id
   where s.stub_id = p_stub_id
     and public.can_see_upcoming(s.user_id)
   order by s.created_at
   limit 200;
$$;
revoke all on function public.stub_holders(text) from public;
grant execute on function public.stub_holders(text) to anon, authenticated;
