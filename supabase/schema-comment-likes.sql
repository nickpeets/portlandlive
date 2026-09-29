-- Hearts on comments (Sep 29 2026, Nick). Run once, in full, in the Supabase
-- SQL Editor. Re-running is safe. Depends on schema-comments.sql,
-- schema-blocks.sql (is_blocked_between), schema-profile-pages.sql
-- (rate_limit_take). Same shape as photo likes: counts are public, who
-- liked is never listed, and your bell gets "Anita and 2 others liked your
-- comment". Works on every comment thread: shows, Liner Notes, ghost pages.

create table if not exists public.comment_likes (
  comment_id uuid not null references public.comments (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (comment_id, user_id)
);
create index if not exists comment_likes_comment_idx on public.comment_likes (comment_id, created_at desc);
alter table public.comment_likes enable row level security;
revoke all on public.comment_likes from anon, authenticated;

-- Toggle your heart. Returns the new count and whether you now like it.
create or replace function public.comment_like(p_id uuid, p_on boolean)
returns table (likes integer, liked boolean)
language plpgsql security definer set search_path = public as $$
declare v_owner uuid;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not public.rate_limit_take('comment_like', 200) then raise exception 'rate_limited' using errcode = 'P0001'; end if;
  select c.user_id into v_owner from public.comments c where c.id = p_id;
  if v_owner is null then raise exception 'not_found' using errcode = 'P0001'; end if;
  if public.is_blocked_between(auth.uid(), v_owner) then raise exception 'blocked' using errcode = 'P0001'; end if;
  if p_on then
    insert into public.comment_likes (comment_id, user_id) values (p_id, auth.uid()) on conflict do nothing;
  else
    delete from public.comment_likes l where l.comment_id = p_id and l.user_id = auth.uid();
  end if;
  return query
    select (select count(*)::integer from public.comment_likes l where l.comment_id = p_id),
           exists (select 1 from public.comment_likes l where l.comment_id = p_id and l.user_id = auth.uid());
end; $$;
revoke all on function public.comment_like(uuid, boolean) from public;
grant execute on function public.comment_like(uuid, boolean) to authenticated;

-- Counts for a page of comments, plus which ones you liked. Anyone can read
-- counts; "liked" is false when signed out.
create or replace function public.comment_likes_for(p_ids uuid[])
returns table (comment_id uuid, likes integer, liked boolean)
language sql security definer set search_path = public stable as $$
  select l.comment_id, count(*)::integer,
         coalesce(bool_or(l.user_id = auth.uid()), false)
    from public.comment_likes l
   where l.comment_id = any(coalesce(p_ids, '{}'::uuid[]))
     and cardinality(coalesce(p_ids, '{}'::uuid[])) <= 500
   group by l.comment_id;
$$;
revoke all on function public.comment_likes_for(uuid[]) from public;
grant execute on function public.comment_likes_for(uuid[]) to anon, authenticated;

-- Your bell: one row per comment of yours that other people liked.
create or replace function public.my_comment_likes(p_limit integer default 30)
returns table (comment_id uuid, show_slug text, body text, n integer,
               last_at timestamptz, last_user_id uuid, last_name text, last_handle text)
language sql security definer set search_path = public stable as $$
  with l as (
    select l.comment_id, l.user_id, l.created_at
      from public.comment_likes l
      join public.comments c on c.id = l.comment_id
     where c.user_id = auth.uid()
       and l.user_id <> auth.uid()
       and not public.is_blocked_between(auth.uid(), l.user_id)
  ),
  g as (
    select comment_id, count(*)::integer as n, max(created_at) as last_at from l group by comment_id
  )
  select g.comment_id, c.show_slug, left(c.body, 140), g.n, g.last_at,
         lu.user_id, p.display_name, p.handle
    from g
    join public.comments c on c.id = g.comment_id
    cross join lateral (select l.user_id from l where l.comment_id = g.comment_id
                         order by l.created_at desc limit 1) lu
    left join public.profiles p on p.id = lu.user_id
   where auth.uid() is not null
   order by g.last_at desc
   limit greatest(1, least(coalesce(p_limit, 30), 100));
$$;
revoke all on function public.my_comment_likes(integer) from public;
grant execute on function public.my_comment_likes(integer) to authenticated;

-- Check: the three functions exist.
select proname from pg_proc where proname in ('comment_like', 'comment_likes_for', 'my_comment_likes') order by proname;
