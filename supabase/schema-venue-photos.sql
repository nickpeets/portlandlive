-- Venue photos (Sep 24 2026, Nick). A moderator sets a photo for a venue from
-- its page; it shows at the top of the venue page and is the venue's share
-- image. Stored in the existing "posters" bucket under venues/ (public read,
-- moderator write -- see schema-posters.sql). Run once in the Supabase SQL
-- Editor; re-running is safe.
create table if not exists public.venue_photos (
  venue text primary key check (char_length(venue) between 1 and 200),
  image_url text not null check (char_length(image_url) <= 1000),
  set_by uuid references auth.users (id) on delete set null,
  updated_at timestamptz not null default now()
);
alter table public.venue_photos enable row level security;
revoke all on public.venue_photos from anon, authenticated;

-- Set (or clear, with null) a venue's photo. Moderators only.
create or replace function public.set_venue_photo(p_venue text, p_image_url text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_moderator() then raise exception 'not a moderator' using errcode = 'insufficient_privilege'; end if;
  if p_image_url is null or btrim(p_image_url) = '' then
    delete from public.venue_photos where venue = p_venue;
    return;
  end if;
  insert into public.venue_photos (venue, image_url, set_by, updated_at)
  values (p_venue, p_image_url, auth.uid(), now())
  on conflict (venue) do update set image_url = excluded.image_url, set_by = excluded.set_by, updated_at = now();
end; $$;
revoke all on function public.set_venue_photo(text, text) from public;
grant execute on function public.set_venue_photo(text, text) to authenticated;

-- Anyone can read them: the venue page shows its own, the build uses them
-- for venue share pages.
create or replace function public.venue_photo(p_venue text)
returns text language sql security definer set search_path = public stable as $$
  select v.image_url from public.venue_photos v where v.venue = p_venue;
$$;
revoke all on function public.venue_photo(text) from public;
grant execute on function public.venue_photo(text) to anon, authenticated;

create or replace function public.venue_photos_all()
returns table (venue text, image_url text)
language sql security definer set search_path = public stable as $$
  select v.venue, v.image_url from public.venue_photos v;
$$;
revoke all on function public.venue_photos_all() from public;
grant execute on function public.venue_photos_all() to anon, authenticated;

select count(*) as venue_photos from public.venue_photos;
