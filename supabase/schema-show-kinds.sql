-- Moderator "what is this?" override (Sep 22 2026). Run once, in full, in the
-- Supabase SQL Editor. Re-running is safe. Depends on schema-reporting.sql
-- (is_moderator).
--
-- Nick: talks and other non-music nights keep slipping past the title
-- filters. On any show page a moderator can mark it Music, Comedy or Not
-- music; the page applies it at once for everyone and the nightly build
-- bakes it into the feed.

create table if not exists public.show_kinds (
  slug text primary key check (char_length(slug) between 1 and 300),
  kind text not null check (kind in ('music', 'comedy', 'other')),
  set_by uuid references auth.users (id) on delete set null,
  set_at timestamptz not null default now()
);
alter table public.show_kinds enable row level security;
revoke all on public.show_kinds from anon, authenticated;

create or replace function public.show_kinds_all()
returns table (slug text, kind text)
language sql security definer set search_path = public stable as $$
  select slug, kind from public.show_kinds;
$$;
revoke all on function public.show_kinds_all() from public;
grant execute on function public.show_kinds_all() to anon, authenticated;

-- p_kind null clears the override.
create or replace function public.set_show_kind(p_slug text, p_kind text)
returns boolean
language plpgsql security definer set search_path = public as $$
begin
  if not public.is_moderator() then raise exception 'not a moderator' using errcode = 'insufficient_privilege'; end if;
  if p_kind is null then
    delete from public.show_kinds where slug = p_slug;
  elsif p_kind in ('music', 'comedy', 'other') then
    insert into public.show_kinds (slug, kind, set_by) values (p_slug, p_kind, auth.uid())
    on conflict (slug) do update set kind = excluded.kind, set_by = excluded.set_by, set_at = now();
  else
    raise exception 'bad kind' using errcode = 'P0001';
  end if;
  return true;
end; $$;
revoke all on function public.set_show_kind(text, text) from public;
grant execute on function public.set_show_kind(text, text) to authenticated;

select proname from pg_proc where proname in ('show_kinds_all', 'set_show_kind') order by proname;
