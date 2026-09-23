-- Email when someone asks to follow you (Sep 23 2026). Run once, in full, in
-- the Supabase SQL Editor. Re-running is safe. Depends on
-- schema-follow-requests.sql, schema-dm-email.sql (the shared email switch,
-- unsubscribe token) and schema-submissions-email.sql (_ros_send_email).
--
-- Nick: "do members get an email when someone requests a follow?" -> now yes.
--   * a request waiting 10+ minutes gets an email (so a quick approve on the
--     site, or an undo by the asker, sends nothing)
--   * each request is emailed once; requests that pile up between sweeps go
--     out together ("Anita, Tim and 2 others want to follow you")
--   * only requests from the last 7 days, so switching this on never mails a
--     backlog
--   * shares the "Email me about messages and follow requests" switch and the
--     unsubscribe link with message emails
-- A pg_cron job runs it every 5 minutes.

create table if not exists public.follow_email_state (
  follower_id uuid not null references auth.users (id) on delete cascade,
  followee_id uuid not null references auth.users (id) on delete cascade,
  emailed_at timestamptz not null default now(),
  primary key (follower_id, followee_id)
);
alter table public.follow_email_state enable row level security;
revoke all on public.follow_email_state from anon, authenticated;

create or replace function public.follow_email_sweep()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  r record; n integer := 0; v_token uuid; v_who text; v_subject text; v_names text[]; v_count integer;
begin
  for r in
    select f.followee_id as recipient, u.email,
           array_agg(f.follower_id order by f.created_at) as askers
      from public.follows f
      join auth.users u on u.id = f.followee_id
      left join public.dm_email_prefs ep on ep.user_id = f.followee_id
     where f.status = 'pending'
       and f.created_at <= now() - interval '10 minutes'
       and f.created_at >  now() - interval '7 days'
       and coalesce(ep.enabled, true)
       and coalesce(u.email, '') <> ''
       and not exists (select 1 from public.follow_email_state s
                        where s.follower_id = f.follower_id and s.followee_id = f.followee_id)
     group by f.followee_id, u.email
  loop
    select array_agg(x.label order by x.ord), count(*)::integer
      into v_names, v_count
      from (select coalesce(nullif(p.display_name, ''), p.handle)
                   || case when p.handle is not null then ' (@' || p.handle || ')' else '' end as label,
                   a.ord
              from unnest(r.askers) with ordinality as a(uid, ord)
              join public.profiles p on p.id = a.uid) x;
    if coalesce(v_count, 0) = 0 then continue; end if;

    v_who := case
      when v_count = 1 then v_names[1]
      when v_count = 2 then v_names[1] || ' and ' || v_names[2]
      else v_names[1] || ', ' || v_names[2] || ' and ' || (v_count - 2) || ' other' || case when v_count - 2 = 1 then '' else 's' end
    end;
    v_subject := case when v_count = 1
      then split_part(v_names[1], ' (@', 1) || ' wants to follow you on Rain Or Shows'
      else v_count || ' people want to follow you on Rain Or Shows' end;
    v_who := replace(replace(replace(v_who, '&', '&amp;'), '<', '&lt;'), '>', '&gt;');

    insert into public.dm_email_prefs (user_id) values (r.recipient) on conflict do nothing;
    select unsub_token into v_token from public.dm_email_prefs where user_id = r.recipient;

    perform public._ros_send_email(
      r.email,
      v_subject,
      '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#222;max-width:560px">'
      || '<p><strong>' || v_who || '</strong> ' || case when v_count = 1 then 'wants' else 'want' end || ' to follow you on Rain Or Shows.</p>'
      || '<p style="margin:18px 0"><a href="https://rainorshows.com/#/requests" '
      || 'style="background:#b5562b;color:#fff;text-decoration:none;padding:10px 18px;border-radius:999px;display:inline-block">Approve or decline</a></p>'
      || '<p style="font-size:12px;color:#999">You get one email per request. '
      || '<a href="https://rainorshows.com/#/unsubscribe/' || v_token || '" style="color:#999">Turn off message and follow-request emails</a></p></div>');

    insert into public.follow_email_state (follower_id, followee_id)
    select a, r.recipient from unnest(r.askers) as a
    on conflict do nothing;
    n := n + 1;
  end loop;
  return n;
end;
$$;
revoke all on function public.follow_email_sweep() from public, anon, authenticated;

create extension if not exists pg_cron;
select cron.unschedule(jobid) from cron.job where jobname = 'follow-email-sweep';
select cron.schedule('follow-email-sweep', '*/5 * * * *', 'select public.follow_email_sweep()');

-- Check: the job is scheduled.
select jobname, schedule, command from cron.job where jobname = 'follow-email-sweep';
