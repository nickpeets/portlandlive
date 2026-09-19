-- Photo credit in the lightbox (Sep 18 2026): latest_photos returns the
-- uploader's display name so the home-feed strip can say "Photo by …".
-- (photos_for_show already does.) Run once in the Supabase SQL Editor.
drop function if exists public.latest_photos(integer);
create or replace function public.latest_photos(p_limit integer default 20)
returns table (id uuid, show_slug text, path text, width integer, height integer, title text, venue text, show_date text, created_at timestamptz, kind text, video_path text, display_name text)
language sql security definer set search_path = public stable as $$
  select ph.id, ph.show_slug, ph.path, ph.width, ph.height, ph.title, ph.venue, ph.show_date, ph.created_at, ph.kind, ph.video_path, p.display_name
    from public.show_photos ph left join public.profiles p on p.id = ph.user_id
   where ph.created_at > now() - interval '21 days'
     and not exists (select 1 from public.content_reports r where r.target_type = 'photo' and r.target_id = ph.id and (r.status is null or r.status = 'upheld'))
   order by ph.created_at desc limit greatest(1, least(coalesce(p_limit, 20), 60));
$$;
revoke all on function public.latest_photos(integer) from public;
grant execute on function public.latest_photos(integer) to anon, authenticated;
