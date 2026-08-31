-- PortlandLive — Stage 1 amendment: display names become unique
--
-- Run this once, in full, in the Supabase SQL Editor. It reverses the original
-- Stage 1 decision (schema.sql: "display_name is NOT unique, NOT a handle").
-- Uniqueness is case-insensitive and whitespace-trimmed, so "Nick P",
-- "nick p" and "  NICK P  " are the same name.
--
-- This is NOT retroactive. comments.display_name and ticket_posts.display_name
-- are denormalized snapshots frozen at post time and are deliberately left
-- alone: an old comment keeps the name its author had when they wrote it.
-- Only new signups (and a future rename feature, which does not exist yet)
-- are affected.

-- 1. Refuse to proceed if existing accounts already collide, with a message
--    naming them, rather than letting the index build fail opaquely.
do $$
declare
  dupes text;
begin
  select string_agg(format('%s (%s accounts)', name, n), '; ' order by name)
    into dupes
    from (
      select lower(trim(display_name)) as name, count(*) as n
        from public.profiles
       group by 1
      having count(*) > 1
    ) d;

  if dupes is not null then
    raise exception
      'Cannot make display_name unique: these names are already shared -- %. Resolve by hand (rename the duplicate accounts in public.profiles), then re-run this migration.',
      dupes
      using errcode = 'unique_violation';
  end if;
end;
$$;

-- 2. The constraint itself. Expression index on lower(trim(...)), which is
--    what makes it case- and whitespace-insensitive.
create unique index if not exists profiles_display_name_unique_idx
  on public.profiles (lower(trim(display_name)));

-- 3. Signup path. The Stage 1 trigger inserts the profile row inside the
--    auth.users insert, so a collision aborts the whole signup -- which is the
--    behaviour we want (no account left without a profile). But the error that
--    reaches the browser through GoTrue is a generic database error, which is
--    not something to show a person. Re-raise with a token the client can
--    recognise, and keep the original Stage 1 behaviour otherwise.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    coalesce(nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''), 'New user')
  );
  return new;
exception
  when unique_violation then
    raise exception 'display_name_taken'
      using errcode = 'unique_violation';
end;
$$;

-- 4. RLS makes an honest pre-check impossible from the client: anon has no
--    privileges on profiles at all, and profiles_select_own limits an
--    authenticated user to their OWN row -- so "select where display_name = ?"
--    returns zero rows for everyone and would report every name as free.
--    This SECURITY DEFINER function is the only way to ask the question
--    without opening the table up. It answers exactly one yes/no about a name
--    the caller already typed, and returns no rows, ids or other names.
create or replace function public.display_name_available(candidate text)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select not exists (
    select 1 from public.profiles
     where lower(trim(display_name)) = lower(trim(candidate))
  );
$$;

revoke all on function public.display_name_available(text) from public;
grant execute on function public.display_name_available(text) to anon, authenticated;
