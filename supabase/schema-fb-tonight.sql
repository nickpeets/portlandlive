-- Daily "TONIGHT" Facebook Page post (Nov 25 2026).
--
-- Nick: "We don't want to ever miss a day." The site posts
--   TONIGHT: <act> at <venue>! GO SEE LIVE MUSIC!   (+ the show link)
-- to the Rain Or Shows Page at noon Pacific, every day, with no browser,
-- no computer and no Claude chat involved.
--
--   * The nightly build writes og/tonight/posts.json (tonight_post.py):
--     the biggest music show for each of the next 8 nights.
--   * pg_cron runs fb_tonight_tick() every 5 minutes. From 11:30 it fetches
--     that file, at 12:00 it posts today's entry through the Graph API, and
--     it retries up to 6 times. If it still hasn't posted by 1pm, or there's
--     no show tonight, it emails Nick (Resend, same key as the other mail).
--   * The Page key never leaves the vault. fb_setup() turns the short-lived
--     key from the Graph API Explorer into a never-expiring Page key on the
--     server (fb_setup_step, run by cron each minute until it's done).
--
-- Run once in the SQL Editor. Safe to re-run.

create extension if not exists pg_net;
create extension if not exists pg_cron;

create table if not exists public.fb_config (
  k text primary key,
  v text
);
revoke all on public.fb_config from public, anon, authenticated;

create table if not exists public.fb_tonight (
  day        date primary key,
  status     text not null default 'fetching',  -- fetching|ready|posting|posted|skipped|failed
  message    text,
  link       text,
  fetch_req  bigint,
  post_req   bigint,
  post_id    text,
  tries      int  not null default 0,
  note       text,
  alerted    boolean not null default false,
  updated_at timestamptz not null default now()
);
revoke all on public.fb_tonight from public, anon, authenticated;

create or replace function public._fb_secret(p_name text) returns text
language sql security definer set search_path = public as $$
  select decrypted_secret from vault.decrypted_secrets where name = p_name limit 1
$$;
revoke all on function public._fb_secret(text) from public, anon, authenticated;

create or replace function public._fb_put_secret(p_name text, p_value text) returns void
language plpgsql security definer set search_path = public as $$
declare v_id uuid;
begin
  select id into v_id from vault.secrets where name = p_name;
  if v_id is null then perform vault.create_secret(p_value, p_name);
  else perform vault.update_secret(v_id, p_value); end if;
end; $$;
revoke all on function public._fb_put_secret(text, text) from public, anon, authenticated;

create or replace function public._fb_set(p_k text, p_v text) returns void
language sql security definer set search_path = public as $$
  insert into public.fb_config(k, v) values (p_k, p_v)
  on conflict (k) do update set v = excluded.v
$$;

create or replace function public._fb_get(p_k text) returns text
language sql security definer set search_path = public as $$
  select v from public.fb_config where k = p_k
$$;

create or replace function public._fb_alert(p_subject text, p_body text) returns void
language plpgsql security definer set search_path = public as $$
declare v_key text := public._fb_secret('resend_api_key');
begin
  if v_key is null then return; end if;
  perform net.http_post(
    url := 'https://api.resend.com/emails',
    headers := jsonb_build_object('Authorization', 'Bearer ' || v_key, 'Content-Type', 'application/json'),
    body := jsonb_build_object('from', 'Rain Or Shows <noreply@rainorshows.com>',
                               'to', jsonb_build_array('nickpeets@gmail.com'),
                               'subject', p_subject, 'text', p_body));
end; $$;

------------------------------------------------------------------------------
-- One-time key setup.
--   select public.fb_setup('<key from Graph API Explorer>', '<App secret>');
-- Then wait ~2 minutes and check:  select public._fb_get('setup');
-- It should say: done: Rain Or Shows (page id ...)
------------------------------------------------------------------------------
create or replace function public.fb_setup(p_user_token text, p_app_secret text) returns text
language plpgsql security definer set search_path = public as $$
declare v_req bigint;
begin
  perform public._fb_put_secret('fb_app_secret', trim(p_app_secret));
  v_req := net.http_get(
    url := 'https://graph.facebook.com/v25.0/oauth/access_token',
    params := jsonb_build_object('grant_type', 'fb_exchange_token',
                                 'client_id', '1139798711980377',
                                 'client_secret', trim(p_app_secret),
                                 'fb_exchange_token', trim(p_user_token)),
    timeout_milliseconds := 20000);
  perform public._fb_set('setup', 'exchanging');
  perform public._fb_set('setup_req', v_req::text);
  perform cron.unschedule(jobid) from cron.job where jobname = 'fb-setup';
  perform cron.schedule('fb-setup', '* * * * *', 'select public.fb_setup_step()');
  return 'started -- check select public._fb_get(''setup''); in a minute or two';
end; $$;
revoke all on function public.fb_setup(text, text) from public, anon, authenticated;

create or replace function public.fb_setup_step() returns void
language plpgsql security definer set search_path = public as $$
declare
  v_state text := public._fb_get('setup');
  v_req bigint := nullif(public._fb_get('setup_req'), '')::bigint;
  r record; v_json jsonb; v_page jsonb; v_new bigint;
begin
  if v_state not in ('exchanging', 'listing') then
    perform cron.unschedule(jobid) from cron.job where jobname = 'fb-setup';
    return;
  end if;
  select * into r from net._http_response where id = v_req;
  if not found then return; end if;  -- still waiting
  v_json := case when r.content ~ '^\s*\{' then r.content::jsonb else '{}'::jsonb end;
  if v_json ? 'error' or r.status_code <> 200 then
    perform public._fb_set('setup', 'error: ' || coalesce(v_json #>> '{error,message}', r.error_msg, 'HTTP ' || r.status_code));
    return;
  end if;
  if v_state = 'exchanging' then
    v_new := net.http_get(
      url := 'https://graph.facebook.com/v25.0/me/accounts',
      params := jsonb_build_object('fields', 'id,name,access_token',
                                   'access_token', v_json ->> 'access_token'),
      timeout_milliseconds := 20000);
    perform public._fb_set('setup', 'listing');
    perform public._fb_set('setup_req', v_new::text);
  else
    select p into v_page from jsonb_array_elements(v_json -> 'data') p
      where p ->> 'name' ilike 'Rain Or Shows%' limit 1;
    if v_page is null then
      perform public._fb_set('setup', 'error: the key has no access to the Rain Or Shows Page -- tick it in the popup');
      return;
    end if;
    perform public._fb_put_secret('fb_page_token', v_page ->> 'access_token');
    perform public._fb_set('page_id', v_page ->> 'id');
    perform public._fb_set('setup', 'done: ' || (v_page ->> 'name') || ' (page id ' || (v_page ->> 'id') || ')');
    perform cron.unschedule(jobid) from cron.job where jobname = 'fb-setup';
  end if;
end; $$;
revoke all on function public.fb_setup_step() from public, anon, authenticated;

------------------------------------------------------------------------------
-- Daily post. Every 5 minutes; does nothing outside 11:30am-1:59pm Pacific.
------------------------------------------------------------------------------
create or replace function public.fb_tonight_tick() returns void
language plpgsql security definer set search_path = public as $$
declare
  v_now  timestamp := now() at time zone 'America/Los_Angeles';
  v_day  date := v_now::date;
  v_mins int := extract(hour from v_now)::int * 60 + extract(minute from v_now)::int;
  v_row  public.fb_tonight;
  r record; v_json jsonb; v_post jsonb; v_token text; v_page text; v_req bigint;
begin
  if v_mins < 11 * 60 + 30 or v_mins >= 14 * 60 then return; end if;
  v_token := public._fb_secret('fb_page_token');
  v_page  := public._fb_get('page_id');
  if v_token is null or v_page is null then return; end if;  -- setup not finished

  select * into v_row from public.fb_tonight where day = v_day;
  if not found then
    v_req := net.http_get(url := 'https://rainorshows.com/og/tonight/posts.json',
                          params := jsonb_build_object('cb', extract(epoch from now())::bigint::text),
                          timeout_milliseconds := 20000);
    insert into public.fb_tonight(day, status, fetch_req) values (v_day, 'fetching', v_req);
    return;
  end if;

  -- Still not up by 1pm (or out of retries): tell Nick once, so he can post by hand.
  if v_row.status in ('fetching', 'ready', 'posting') and (v_mins >= 13 * 60 or v_row.tries >= 6)
     and not v_row.alerted then
    update public.fb_tonight set alerted = true, status = case when v_row.tries >= 6 then 'failed' else status end
      where day = v_day;
    perform public._fb_alert('TONIGHT post did NOT go up (' || v_day || ')',
      'Today''s Facebook post failed: ' || coalesce(v_row.note, 'no reason given') || E'\n\n'
      || 'Post this by hand: ' || coalesce(v_row.message, '(no show picked)') || ' ' || coalesce(v_row.link, '')
      || E'\n\nhttps://business.facebook.com/latest/composer?asset_id=' || v_page);
  end if;

  if v_row.status = 'fetching' then
    select * into r from net._http_response where id = v_row.fetch_req;
    if not found then return; end if;
    if r.status_code = 200 and r.content ~ '^\s*\{' then
      v_json := r.content::jsonb;
      select p into v_post from jsonb_array_elements(v_json -> 'posts') p
        where p ->> 'date' = v_day::text limit 1;
      if v_post is null then
        update public.fb_tonight set status = 'skipped', note = 'no music show tonight in posts.json',
          updated_at = now() where day = v_day;
        perform public._fb_alert('No TONIGHT post today (' || v_day || ')',
          'There was no music show tonight in the listings, so nothing went up on the Page. Post one by hand if you want: https://business.facebook.com/latest/composer?asset_id=' || v_page);
        update public.fb_tonight set alerted = true where day = v_day;
      else
        update public.fb_tonight set status = 'ready', message = v_post ->> 'message',
          link = v_post ->> 'link', updated_at = now() where day = v_day;
      end if;
    else
      -- refetch on the next tick
      v_req := net.http_get(url := 'https://rainorshows.com/og/tonight/posts.json',
                            params := jsonb_build_object('cb', extract(epoch from now())::bigint::text),
                            timeout_milliseconds := 20000);
      update public.fb_tonight set fetch_req = v_req, tries = tries + 1,
        note = 'posts.json fetch: ' || coalesce(r.error_msg, 'HTTP ' || r.status_code), updated_at = now()
        where day = v_day;
    end if;
    return;
  end if;

  if v_row.status = 'ready' and v_mins >= 12 * 60 and v_row.tries < 6 then
    v_req := net.http_post(
      url := 'https://graph.facebook.com/v25.0/' || v_page || '/feed',
      body := jsonb_build_object('message', v_row.message, 'link', v_row.link, 'access_token', v_token),
      timeout_milliseconds := 30000);
    update public.fb_tonight set status = 'posting', post_req = v_req, tries = tries + 1, updated_at = now()
      where day = v_day;
    return;
  end if;

  if v_row.status = 'posting' then
    select * into r from net._http_response where id = v_row.post_req;
    if not found then return; end if;
    v_json := case when r.content ~ '^\s*\{' then r.content::jsonb else '{}'::jsonb end;
    if v_json ? 'id' then
      update public.fb_tonight set status = 'posted', post_id = v_json ->> 'id', note = null,
        updated_at = now() where day = v_day;
    else
      update public.fb_tonight set status = 'ready',
        note = coalesce(v_json #>> '{error,message}', r.error_msg, 'HTTP ' || r.status_code),
        updated_at = now() where day = v_day;
    end if;
    return;
  end if;

end; $$;
revoke all on function public.fb_tonight_tick() from public, anon, authenticated;

select cron.unschedule(jobid) from cron.job where jobname = 'fb-tonight';
select cron.schedule('fb-tonight', '*/5 * * * *', 'select public.fb_tonight_tick()');

-- Nov 25 2026's post (Saosin) is already queued in the Facebook Planner.
insert into public.fb_tonight(day, status, note)
values ('2026-11-25', 'posted', 'queued by hand in Meta Planner')
on conflict (day) do nothing;
