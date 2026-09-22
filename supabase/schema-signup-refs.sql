-- Where sign-ups come from (Sep 22 2026). Run once, in full, in the Supabase
-- SQL Editor. Re-running is safe.
--
-- Nick: give each Facebook post its own link, rainorshows.com/?ref=fb-weekend,
-- and see which posts bring sign-ups. The page remembers the FIRST ?ref= a
-- visitor arrived with (30 days, on their device) and reports it once, right
-- after they create an account. Only accounts made in the last day are
-- credited, so an old member signing in from a post never counts.

create table if not exists public.signup_refs (
  user_id uuid primary key references auth.users (id) on delete cascade,
  ref text not null check (char_length(ref) between 1 and 60),
  first_seen timestamptz,
  created_at timestamptz not null default now()
);
alter table public.signup_refs enable row level security;
revoke all on public.signup_refs from anon, authenticated;

create or replace function public.record_signup_ref(p_ref text, p_first_seen timestamptz default null)
returns boolean
language plpgsql security definer set search_path = public as $$
declare v_ref text := lower(regexp_replace(coalesce(p_ref, ''), '[^a-zA-Z0-9_-]', '', 'g'));
begin
  if auth.uid() is null or v_ref = '' then return false; end if;
  if not exists (select 1 from auth.users u where u.id = auth.uid() and u.created_at > now() - interval '1 day') then
    return false;   -- not a new account
  end if;
  insert into public.signup_refs (user_id, ref, first_seen)
  values (auth.uid(), left(v_ref, 60), p_first_seen)
  on conflict (user_id) do nothing;
  return true;
end; $$;
revoke all on function public.record_signup_ref(text, timestamptz) from public;
grant execute on function public.record_signup_ref(text, timestamptz) to authenticated;

-- The report: which links brought sign-ups. Run this any time.
select ref,
       count(*) as signups,
       count(*) filter (where created_at > now() - interval '7 days') as last_7_days,
       max(created_at) as latest
  from public.signup_refs
 group by ref
 order by signups desc;
