-- Weekly newsletter (Nick Nov 19 2026; rebuilt Nov 25 2026).
--
-- Every Thursday at 9am Pacific, every Rain Or Shows account holder gets the
-- week's shows. The nightly build writes og/newsletter/latest.html
-- (newsletter.py); this fetches it and sends it to the Resend "Members"
-- segment as a BROADCAST (free marketing tier, not the 100/day cap; Resend
-- handles the unsubscribe link). Same key and segment as the miracle alerts
-- (schema-miracle-alerts.sql must be run first).
--
-- A page whose <meta name="ros-week"> isn't today's date is never sent (the
-- build didn't run): Nick gets an email instead. Run once. Safe to re-run.

create table if not exists public.newsletter_sends (
  week       date primary key,
  status     text not null default 'fetching',  -- fetching|sending|sent|failed
  subject    text,
  fetch_req  bigint,
  send_req   bigint,
  broadcast  text,
  tries      int not null default 0,
  note       text,
  alerted    boolean not null default false,
  updated_at timestamptz not null default now()
);
alter table public.newsletter_sends enable row level security;
revoke all on public.newsletter_sends from anon, authenticated;

create or replace function public.newsletter_tick() returns void
language plpgsql security definer set search_path = public as $$
declare
  v_now  timestamp := now() at time zone 'America/Los_Angeles';
  v_day  date := v_now::date;
  v_mins int := extract(hour from v_now)::int * 60 + extract(minute from v_now)::int;
  v_seg  text;
  v_row  public.newsletter_sends;
  r record; v_html text; v_subj text; v_week text; v_json jsonb;
begin
  if extract(dow from v_now) <> 4 or v_mins < 9 * 60 or v_mins >= 11 * 60 then return; end if;
  select trim(decrypted_secret) into v_seg from vault.decrypted_secrets where name = 'resend_members_segment' limit 1;
  if v_seg is null then return; end if;

  select * into v_row from public.newsletter_sends where week = v_day;
  if not found then
    insert into public.newsletter_sends(week, status, fetch_req)
    values (v_day, 'fetching', net.http_get(url := 'https://rainorshows.com/og/newsletter/latest.html',
            params := jsonb_build_object('cb', extract(epoch from now())::bigint::text),
            timeout_milliseconds := 20000));
    return;
  end if;

  -- Not out by 10:30, or out of tries: tell Nick once.
  if v_row.status in ('fetching', 'sending', 'failed') and (v_mins >= 10 * 60 + 30 or v_row.tries >= 4)
     and not v_row.alerted then
    update public.newsletter_sends set alerted = true where week = v_day;
    perform public._fb_alert('Weekly newsletter did NOT go out (' || v_day || ')',
      'The Thursday newsletter failed: ' || coalesce(v_row.note, 'no reason given')
      || E'\n\nPreview: https://rainorshows.com/og/newsletter/latest.html');
    return;
  end if;

  if v_row.status = 'fetching' then
    select * into r from net._http_response where id = v_row.fetch_req;
    if not found then return; end if;
    v_html := r.content;
    v_week := substring(coalesce(v_html, '') from 'name="ros-week" content="([0-9-]+)"');
    if r.status_code <> 200 or v_week is distinct from v_day::text then
      update public.newsletter_sends set tries = tries + 1,
        status = case when tries + 1 >= 4 then 'failed' else 'fetching' end,
        note = case when r.status_code <> 200 then 'page fetch: ' || coalesce(r.error_msg, 'HTTP ' || r.status_code)
                    else 'page is from ' || coalesce(v_week, '?') || ', not today -- the nightly build may not have run' end,
        fetch_req = net.http_get(url := 'https://rainorshows.com/og/newsletter/latest.html',
                      params := jsonb_build_object('cb', extract(epoch from now())::bigint::text),
                      timeout_milliseconds := 20000),
        updated_at = now()
      where week = v_day;
      return;
    end if;
    v_subj := substring(v_html from '<title>(.*?)</title>');
    v_subj := replace(replace(replace(replace(coalesce(v_subj, 'Portland live music this week'),
                '&amp;', '&'), '&#x27;', ''''), '&quot;', '"'), '&lt;', '<');
    update public.newsletter_sends set status = 'sending', subject = v_subj, tries = tries + 1,
      send_req = public._ros_resend('POST', '/broadcasts', jsonb_build_object(
        'segment_id', v_seg,
        'from', 'Rain Or Shows <noreply@rainorshows.com>',
        'subject', v_subj,
        'html', v_html,
        'name', 'Weekly ' || v_day,
        'send', true)),
      updated_at = now()
    where week = v_day;
    return;
  end if;

  if v_row.status = 'sending' then
    select * into r from net._http_response where id = v_row.send_req;
    if not found then return; end if;
    v_json := case when r.content ~ '^\s*\{' then r.content::jsonb else '{}'::jsonb end;
    if r.status_code between 200 and 299 and v_json ? 'id' then
      update public.newsletter_sends set status = 'sent', broadcast = v_json ->> 'id', note = null,
        updated_at = now() where week = v_day;
    else
      update public.newsletter_sends set status = case when tries >= 4 then 'failed' else 'fetching' end,
        note = 'send: ' || coalesce(v_json ->> 'message', r.error_msg, 'HTTP ' || r.status_code),
        fetch_req = net.http_get(url := 'https://rainorshows.com/og/newsletter/latest.html',
                      params := jsonb_build_object('cb', extract(epoch from now())::bigint::text),
                      timeout_milliseconds := 20000),
        updated_at = now() where week = v_day;
    end if;
  end if;
end; $$;
revoke all on function public.newsletter_tick() from public, anon, authenticated;

select cron.unschedule(jobid) from cron.job where jobname = 'newsletter-weekly';
select cron.schedule('newsletter-weekly', '*/5 * * * *', 'select public.newsletter_tick()');
