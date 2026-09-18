-- Ticker lines you write yourself, from the header menu (Sep 18 2026).
--
-- Until now a hand-written ticker line meant editing news.json and pushing.
-- These live here instead: add one from the menu (text + last day it runs),
-- delete it there too. The site's ticker reads them alongside the build's
-- automatic lines, and the build merges them into news.json nightly as
-- well. Moderator-only writes; anyone can read what's running.
--
-- Run once, in full, in the Supabase SQL Editor.

create table if not exists public.ticker_lines (
  id uuid primary key default gen_random_uuid(),
  text text not null,
  run_from date not null default (now() at time zone 'America/Los_Angeles')::date,
  run_until date not null,
  created_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  constraint ticker_lines_text_length check (char_length(btrim(text)) between 1 and 200)
);
alter table public.ticker_lines enable row level security;
revoke all on public.ticker_lines from anon, authenticated;

-- Everyone: the lines running today (the ticker and the build both call this).
create or replace function public.ticker_lines_live()
returns table (id uuid, text text, run_from date, run_until date)
language sql security definer set search_path = public stable as $$
  select t.id, t.text, t.run_from, t.run_until
    from public.ticker_lines t
   where t.run_from <= (now() at time zone 'America/Los_Angeles')::date
     and t.run_until >= (now() at time zone 'America/Los_Angeles')::date
   order by t.created_at desc
   limit 20;
$$;
revoke all on function public.ticker_lines_live() from public;
grant execute on function public.ticker_lines_live() to anon, authenticated;

-- Moderator: everything on file (running, upcoming, expired), for the editor.
create or replace function public.ticker_lines_all()
returns table (id uuid, text text, run_from date, run_until date, created_at timestamptz)
language sql security definer set search_path = public stable as $$
  select t.id, t.text, t.run_from, t.run_until, t.created_at
    from public.ticker_lines t
   where public.is_moderator()
   order by t.created_at desc
   limit 50;
$$;
revoke all on function public.ticker_lines_all() from public;
grant execute on function public.ticker_lines_all() to authenticated;

create or replace function public.ticker_add(p_text text, p_until date)
returns uuid language plpgsql security definer set search_path = public as $$
declare new_id uuid;
begin
  if not public.is_moderator() then raise exception 'not a moderator' using errcode = 'insufficient_privilege'; end if;
  insert into public.ticker_lines (text, run_until, created_by) values (btrim(p_text), p_until, auth.uid()) returning id into new_id;
  return new_id;
end; $$;
revoke all on function public.ticker_add(text, date) from public;
grant execute on function public.ticker_add(text, date) to authenticated;

create or replace function public.ticker_delete(p_id uuid)
returns boolean language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  if not public.is_moderator() then raise exception 'not a moderator' using errcode = 'insufficient_privilege'; end if;
  delete from public.ticker_lines where id = p_id;
  get diagnostics n = row_count;
  return n > 0;
end; $$;
revoke all on function public.ticker_delete(uuid) from public;
grant execute on function public.ticker_delete(uuid) to authenticated;

select count(*) as ticker_lines from public.ticker_lines;
