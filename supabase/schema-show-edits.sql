-- Show edits, set inline on a show page by a moderator.
-- Run once, in full, in the Supabase SQL Editor. Re-running is safe.
-- Depends on schema-reporting.sql (is_moderator).
create table if not exists public.show_edits (
  slug       text primary key check (char_length(slug) between 1 and 300),
  title      text check (title is null or char_length(title) between 1 and 200),
  show_time  text check (show_time is null or char_length(show_time) <= 30),
  price      text check (price is null or char_length(price) <= 40),
  age        text check (age is null or age in ('21+', '18+', 'all-ages')),
  link       text check (link is null or (char_length(link) <= 500 and link ~* '^https?://')),
  about      text check (about is null or char_length(about) <= 600),
  set_by     uuid references auth.users (id) on delete set null,
  updated_at timestamptz not null default now()
);
alter table public.show_edits enable row level security;
revoke all on public.show_edits from anon, authenticated;

create or replace function public.show_edits_all()
returns table (slug text, title text, show_time text, price text, age text, link text, about text)
language sql security definer set search_path = public stable as $$
  select e.slug, e.title, e.show_time, e.price, e.age, e.link, e.about from public.show_edits e;
$$;
revoke all on function public.show_edits_all() from public;
grant execute on function public.show_edits_all() to anon, authenticated;

create or replace function public.set_show_edit(p_slug text, p_title text, p_time text, p_price text,
                                                p_age text, p_link text, p_about text)
returns boolean
language plpgsql security definer set search_path = public as $$
declare
  t text := nullif(btrim(coalesce(p_title, '')), '');
  tm text := nullif(btrim(coalesce(p_time, '')), '');
  pr text := nullif(btrim(coalesce(p_price, '')), '');
  ag text := nullif(btrim(coalesce(p_age, '')), '');
  ln text := nullif(btrim(coalesce(p_link, '')), '');
  ab text := nullif(btrim(coalesce(p_about, '')), '');
begin
  if not public.is_moderator() then raise exception 'not a moderator' using errcode = 'insufficient_privilege'; end if;
  if p_slug is null or btrim(p_slug) = '' then raise exception 'no show' using errcode = 'P0001'; end if;
  if t is null and tm is null and pr is null and ag is null and ln is null and ab is null then
    delete from public.show_edits where slug = p_slug;
    return true;
  end if;
  insert into public.show_edits (slug, title, show_time, price, age, link, about, set_by, updated_at)
  values (p_slug, t, tm, pr, ag, ln, ab, auth.uid(), now())
  on conflict (slug) do update set title = excluded.title, show_time = excluded.show_time,
    price = excluded.price, age = excluded.age, link = excluded.link, about = excluded.about,
    set_by = excluded.set_by, updated_at = now();
  return true;
end; $$;
revoke all on function public.set_show_edit(text, text, text, text, text, text, text) from public;
grant execute on function public.set_show_edit(text, text, text, text, text, text, text) to authenticated;

select proname from pg_proc where proname in ('show_edits_all', 'set_show_edit') order by proname;
