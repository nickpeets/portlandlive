-- Stories, part 3 (Sep 29 2026): scheduled posts. Run once, in full, in the
-- Supabase SQL Editor. Re-running is safe. Depends on schema-stories.sql.
--
-- Nick: "post and have them appear at the time we select." A scheduled story
-- is a published story whose published_at is still in the future. Nothing
-- has to run at that moment: every read below shows a story to readers only
-- once published_at has passed, so it appears on the minute by itself.
-- Writers see scheduled stories on the desk the whole time.

create or replace function public.stories_list()
returns table (id uuid, slug text, title text, cover_url text, status text, published_at timestamptz,
               updated_at timestamptz, author_handle text, author_name text, author_id uuid)
language sql security definer set search_path = public stable as $$
  select s.id, s.slug, s.title, s.cover_url, s.status, s.published_at, s.updated_at,
         p.handle, p.display_name, s.author_id
    from public.stories s join public.profiles p on p.id = s.author_id
   where public.stories_visible()
     and ((s.status = 'published' and s.published_at <= now()) or public.is_writer())
   order by coalesce(s.published_at, s.updated_at) desc
   limit 200;
$$;

create or replace function public.story_get(p_key text)
returns table (id uuid, slug text, title text, cover_url text, body jsonb, status text, published_at timestamptz,
               updated_at timestamptz, author_handle text, author_name text, author_id uuid, can_edit boolean)
language sql security definer set search_path = public stable as $$
  select s.id, s.slug, s.title, s.cover_url, s.body, s.status, s.published_at, s.updated_at,
         p.handle, p.display_name, s.author_id,
         public.is_writer()
    from public.stories s join public.profiles p on p.id = s.author_id
   where public.stories_visible()
     and (s.slug = p_key or s.id::text = p_key)
     and ((s.status = 'published' and s.published_at <= now()) or public.is_writer())
   limit 1;
$$;

-- Publish now / unpublish. Publishing a scheduled story now moves its time
-- to now; unpublishing one that never went live forgets its time, so a
-- later Publish doesn't quietly reuse an old future date.
create or replace function public.story_publish(p_id uuid, p_publish boolean)
returns text language plpgsql security definer set search_path = public as $$
declare v_title text; v_slug text; base text; n int := 1;
begin
  if not public.is_writer() then raise exception 'not a writer' using errcode = 'insufficient_privilege'; end if;
  select title, slug into v_title, v_slug from public.stories where id = p_id;
  if not found then raise exception 'not found' using errcode = 'P0001'; end if;
  if p_publish then
    if coalesce(btrim(v_title), '') = '' then raise exception 'needs a title' using errcode = 'P0001'; end if;
    if v_slug is null then
      base := trim(both '-' from left(regexp_replace(lower(v_title), '[^a-z0-9]+', '-', 'g'), 80));
      if base = '' then base := 'story'; end if;
      v_slug := base;
      while exists (select 1 from public.stories where slug = v_slug) loop
        n := n + 1; v_slug := base || '-' || n;
      end loop;
    end if;
    update public.stories set status = 'published', slug = v_slug,
           published_at = case when published_at is null or published_at > now() then now() else published_at end,
           updated_at = now() where id = p_id;
  else
    update public.stories set status = 'draft',
           published_at = case when published_at > now() then null else published_at end,
           updated_at = now() where id = p_id;
  end if;
  return v_slug;
end; $$;
revoke all on function public.story_publish(uuid, boolean) from public;
grant execute on function public.story_publish(uuid, boolean) to authenticated;

-- Schedule (or reschedule): publish with a future time. Returns the slug.
create or replace function public.story_schedule(p_id uuid, p_at timestamptz)
returns text language plpgsql security definer set search_path = public as $$
declare v_slug text;
begin
  if not public.is_writer() then raise exception 'not a writer' using errcode = 'insufficient_privilege'; end if;
  if p_at is null or p_at <= now() + interval '1 minute' then raise exception 'pick a time in the future' using errcode = 'P0001'; end if;
  if p_at > now() + interval '366 days' then raise exception 'that is more than a year out' using errcode = 'P0001'; end if;
  v_slug := public.story_publish(p_id, true);
  update public.stories set published_at = p_at, updated_at = now() where id = p_id;
  return v_slug;
end; $$;
revoke all on function public.story_schedule(uuid, timestamptz) from public;
grant execute on function public.story_schedule(uuid, timestamptz) to authenticated;

-- Check: the desk, with anything scheduled.
select s.title, s.status, s.published_at, s.published_at > now() as scheduled
  from public.stories s order by coalesce(s.published_at, s.updated_at) desc limit 10;
