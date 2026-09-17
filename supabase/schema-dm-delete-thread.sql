-- Delete a conversation (Sep 17 2026).
--
-- Per person, not per thread: deleting hides the conversation from YOUR
-- inbox and leaves the other person's copy alone. It stays hidden until
-- something new arrives after the moment you deleted it -- a fresh message
-- from them brings it back, showing only what came after. dm_messages
-- (yours to read) also honours the cutoff so the old history stays gone
-- for you.
--
-- Run once, in full, in the Supabase SQL Editor.

create table if not exists public.dm_hidden (
  thread_id uuid not null references public.dm_threads (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  hidden_at timestamptz not null default now(),
  primary key (thread_id, user_id)
);
alter table public.dm_hidden enable row level security;
revoke all on public.dm_hidden from anon, authenticated;

create or replace function public.dm_delete_thread(p_thread uuid)
returns boolean language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not exists (select 1 from public.dm_threads where id = p_thread and auth.uid() in (user_a, user_b)) then
    raise exception 'not_allowed' using errcode = 'P0001';
  end if;
  insert into public.dm_hidden (thread_id, user_id, hidden_at) values (p_thread, auth.uid(), now())
    on conflict (thread_id, user_id) do update set hidden_at = excluded.hidden_at;
  return true;
end;
$$;
revoke all on function public.dm_delete_thread(uuid) from public;
grant execute on function public.dm_delete_thread(uuid) to authenticated;

-- Conversations: skip a thread the caller hid unless a message arrived after.
create or replace function public.dm_threads_mine(p_limit integer default 100)
returns table (thread_id uuid, other_id uuid, handle text, display_name text, avatar_url text,
               last_at timestamptz, last_body text, last_sender uuid, unread boolean)
language sql security definer set search_path = public stable as $$
  select t.id,
         case when t.user_a = auth.uid() then t.user_b else t.user_a end as other_id,
         p.handle, p.display_name, p.avatar_url,
         t.last_at,
         (select m.body from public.dm_messages m where m.thread_id = t.id order by m.created_at desc limit 1),
         (select m.sender_id from public.dm_messages m where m.thread_id = t.id order by m.created_at desc limit 1),
         exists (select 1 from public.dm_messages m
                  where m.thread_id = t.id and m.sender_id <> auth.uid()
                    and m.created_at > coalesce((select r.last_read_at from public.dm_reads r where r.thread_id = t.id and r.user_id = auth.uid()), 'epoch'::timestamptz))
    from public.dm_threads t
    join public.profiles p on p.id = case when t.user_a = auth.uid() then t.user_b else t.user_a end
   where auth.uid() in (t.user_a, t.user_b)
     and t.last_at > coalesce((select h.hidden_at from public.dm_hidden h where h.thread_id = t.id and h.user_id = auth.uid()), 'epoch'::timestamptz)
   order by t.last_at desc
   limit greatest(1, least(coalesce(p_limit, 100), 500));
$$;

-- Messages: only what came after the caller's delete, if any.
create or replace function public.dm_messages(p_thread uuid, p_limit integer default 200)
returns table (id bigint, sender_id uuid, body text, created_at timestamptz)
language plpgsql security definer set search_path = public as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  if not exists (select 1 from public.dm_threads where dm_threads.id = p_thread and auth.uid() in (user_a, user_b)) then
    raise exception 'not_allowed' using errcode = 'P0001';
  end if;
  insert into public.dm_reads (thread_id, user_id, last_read_at) values (p_thread, auth.uid(), now())
    on conflict (thread_id, user_id) do update set last_read_at = excluded.last_read_at;
  return query
    select m.id, m.sender_id, m.body, m.created_at
      from public.dm_messages m
     where m.thread_id = p_thread
       and m.created_at > coalesce((select h.hidden_at from public.dm_hidden h where h.thread_id = p_thread and h.user_id = auth.uid()), 'epoch'::timestamptz)
     order by m.created_at desc
     limit greatest(1, least(coalesce(p_limit, 200), 500));
end; $$;
