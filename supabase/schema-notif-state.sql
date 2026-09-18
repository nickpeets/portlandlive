-- Read state for notifications follows the account, not the browser
-- (Sep 18 2026 -- Nick cleared the bell on desktop, the phone still showed
-- the badge). One row per user: the keys already seen (with the time they
-- were seen) and the Clear timestamp. The client merges it with what the
-- browser remembers, then writes back what it learns.
--
-- Run once, in full, in the Supabase SQL Editor.

create table if not exists public.notif_state (
  user_id uuid primary key references auth.users (id) on delete cascade,
  seen jsonb not null default '{}'::jsonb,
  cleared_at timestamptz,
  updated_at timestamptz not null default now()
);
alter table public.notif_state enable row level security;
revoke all on public.notif_state from anon, authenticated;

create or replace function public.notif_state_get()
returns table (seen jsonb, cleared_at timestamptz)
language sql security definer set search_path = public stable as $$
  select s.seen, s.cleared_at from public.notif_state s where s.user_id = auth.uid();
$$;
revoke all on function public.notif_state_get() from public;
grant execute on function public.notif_state_get() to authenticated;

-- Merge: keys are unioned (newer timestamp wins), cleared_at keeps the later.
-- seen is capped at 400 keys, newest kept, so the row never grows unbounded.
create or replace function public.notif_state_merge(p_seen jsonb, p_cleared_at timestamptz)
returns void language plpgsql security definer set search_path = public as $$
declare cur jsonb; merged jsonb;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  insert into public.notif_state (user_id, seen, cleared_at) values (auth.uid(), '{}'::jsonb, null)
    on conflict (user_id) do nothing;
  select seen into cur from public.notif_state where user_id = auth.uid();
  select coalesce(jsonb_object_agg(k, v), '{}'::jsonb) into merged
    from (
      select k, max(v) as v from (
        select key as k, value #>> '{}' as v from jsonb_each(coalesce(cur, '{}'::jsonb))
        union all
        select key as k, value #>> '{}' as v from jsonb_each(coalesce(p_seen, '{}'::jsonb))
      ) u group by k order by max(v) desc limit 400
    ) t;
  update public.notif_state
     set seen = merged,
         cleared_at = greatest(cleared_at, p_cleared_at),
         updated_at = now()
   where user_id = auth.uid();
end; $$;
revoke all on function public.notif_state_merge(jsonb, timestamptz) from public;
grant execute on function public.notif_state_merge(jsonb, timestamptz) to authenticated;
