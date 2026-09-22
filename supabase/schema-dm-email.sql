-- Email when a direct message sits unread (Sep 22 2026).
--
-- Nick: "should messages be notified to email?" -> yes, with guardrails:
--   * only after a message has been unread for 15 minutes
--   * one email per conversation until the person reads it (five messages
--     in a row = one email)
--   * no message text in the email -- just who wrote and a button that
--     opens the conversation
--   * off switch in the bookmark menu ("Email me about new messages", on by
--     default) and an unsubscribe link in every email
--   * only messages from the last 24 hours, so turning this on never mails
--     out an old backlog
--
-- Sends through _ros_send_email (schema-submissions-email.sql: Resend key in
-- the vault, pg_net). A pg_cron job runs the sweep every 5 minutes.
-- Run once, in full, in the Supabase SQL Editor. Re-running is safe.

create table if not exists public.dm_email_prefs (
  user_id uuid primary key references auth.users (id) on delete cascade,
  enabled boolean not null default true,
  unsub_token uuid not null default gen_random_uuid() unique,
  updated_at timestamptz not null default now()
);
alter table public.dm_email_prefs enable row level security;
revoke all on public.dm_email_prefs from anon, authenticated;

create table if not exists public.dm_email_state (
  thread_id uuid not null references public.dm_threads (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  last_emailed_at timestamptz not null,
  primary key (thread_id, user_id)
);
alter table public.dm_email_state enable row level security;
revoke all on public.dm_email_state from anon, authenticated;

-- The sweep. Returns how many emails it sent.
create or replace function public.dm_email_sweep()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  r record; n integer := 0;
  v_name text; v_handle text; v_token uuid; v_esc text;
begin
  for r in
    select t.id as thread_id, u.id as recipient, u.email,
           (select m.sender_id from public.dm_messages m
             where m.thread_id = t.id and m.sender_id <> u.id
             order by m.created_at desc limit 1) as sender
      from public.dm_threads t
      cross join lateral (values (t.user_a), (t.user_b)) as x(uid)
      join auth.users u on u.id = x.uid
      left join public.dm_reads rd on rd.thread_id = t.id and rd.user_id = u.id
      left join public.dm_email_state es on es.thread_id = t.id and es.user_id = u.id
      left join public.dm_email_prefs ep on ep.user_id = u.id
     where coalesce(ep.enabled, true)
       and coalesce(u.email, '') <> ''
       and exists (
         select 1 from public.dm_messages m
          where m.thread_id = t.id and m.sender_id <> u.id
            and m.created_at > coalesce(rd.last_read_at, 'epoch'::timestamptz)
            and m.created_at <= now() - interval '15 minutes'
            and m.created_at >  now() - interval '24 hours')
       and (es.last_emailed_at is null
            or es.last_emailed_at < coalesce(rd.last_read_at, 'epoch'::timestamptz))
  loop
    select coalesce(nullif(p.display_name, ''), p.handle), p.handle
      into v_name, v_handle
      from public.profiles p where p.id = r.sender;
    if v_handle is null then continue; end if;

    insert into public.dm_email_prefs (user_id) values (r.recipient) on conflict do nothing;
    select unsub_token into v_token from public.dm_email_prefs where user_id = r.recipient;

    v_esc := replace(replace(replace(v_name, '&', '&amp;'), '<', '&lt;'), '>', '&gt;');
    perform public._ros_send_email(
      r.email,
      v_name || ' sent you a message on Rain Or Shows',
      '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#222;max-width:560px">'
      || '<p><strong>' || v_esc || '</strong> (@' || v_handle || ') sent you a message on Rain Or Shows.</p>'
      || '<p style="margin:18px 0"><a href="https://rainorshows.com/#/messages/' || v_handle || '" '
      || 'style="background:#b5562b;color:#fff;text-decoration:none;padding:10px 18px;border-radius:999px;display:inline-block">Read it</a></p>'
      || '<p style="font-size:12px;color:#999">You get one email per conversation until you read it. '
      || '<a href="https://rainorshows.com/#/unsubscribe/' || v_token || '" style="color:#999">Turn off message emails</a></p></div>');

    insert into public.dm_email_state (thread_id, user_id, last_emailed_at)
    values (r.thread_id, r.recipient, now())
    on conflict (thread_id, user_id) do update set last_emailed_at = now();
    n := n + 1;
  end loop;
  return n;
end;
$$;
revoke all on function public.dm_email_sweep() from public, anon, authenticated;

-- Your switch (bookmark menu). No row = on.
create or replace function public.dm_email_pref_get()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select coalesce((select enabled from public.dm_email_prefs where user_id = auth.uid()), true)
   where auth.uid() is not null;
$$;
revoke all on function public.dm_email_pref_get() from public;
grant execute on function public.dm_email_pref_get() to authenticated;

create or replace function public.dm_email_pref_set(p_enabled boolean)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  insert into public.dm_email_prefs (user_id, enabled) values (auth.uid(), coalesce(p_enabled, true))
  on conflict (user_id) do update set enabled = coalesce(p_enabled, true), updated_at = now();
  return coalesce(p_enabled, true);
end;
$$;
revoke all on function public.dm_email_pref_set(boolean) from public;
grant execute on function public.dm_email_pref_set(boolean) to authenticated;

-- The link in every email. No sign-in needed: the token is the key.
create or replace function public.dm_email_unsubscribe(p_token uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare k integer;
begin
  update public.dm_email_prefs set enabled = false, updated_at = now() where unsub_token = p_token;
  get diagnostics k = row_count;
  return k > 0;
end;
$$;
revoke all on function public.dm_email_unsubscribe(uuid) from public;
grant execute on function public.dm_email_unsubscribe(uuid) to anon, authenticated;

-- Every 5 minutes. If this errors with "extension pg_cron is not available",
-- turn on pg_cron under Database -> Extensions and run from here down again.
create extension if not exists pg_cron;
select cron.unschedule(jobid) from cron.job where jobname = 'dm-email-sweep';
select cron.schedule('dm-email-sweep', '*/5 * * * *', 'select public.dm_email_sweep()');

-- Check: the job is scheduled.
select jobname, schedule, command from cron.job where jobname = 'dm-email-sweep';
