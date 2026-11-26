-- Daily TONIGHT post on Instagram (Nov 26 2026). Run after schema-fb-tonight.sql.
--
-- Nick (Nov 19 2026): the daily TONIGHT posts go to Instagram too, on their
-- own. Instagram needs a picture: the nightly build makes og/tonight/<date>.jpg
-- (tonight_post.make_card). At noon Pacific, ig_tonight_tick() creates the
-- media container and publishes it to @rainorshows, retries up to 4 times and
-- emails Nick if it isn't up by 1pm.
--
-- Key: the Page key from fb_setup() must include instagram_basic and
-- instagram_content_publish. Re-run setup with a new Explorer key (the app
-- secret is already in the vault):
--   select public.fb_setup('<key from Graph API Explorer>', null);
-- fb_setup_step now also saves the linked Instagram account id (ig_user_id).
-- Safe to re-run.

alter table public.fb_tonight add column if not exists image text;
alter table public.fb_tonight add column if not exists ig_message text;  -- Instagram features a different show (Nick, Nov 26 2026)
alter table public.fb_tonight add column if not exists ig_status text;   -- null|container|publishing|posted|failed
alter table public.fb_tonight add column if not exists ig_req bigint;
alter table public.fb_tonight add column if not exists ig_container text;
alter table public.fb_tonight add column if not exists ig_media text;
alter table public.fb_tonight add column if not exists ig_tries int not null default 0;
alter table public.fb_tonight add column if not exists ig_note text;
alter table public.fb_tonight add column if not exists ig_alerted boolean not null default false;

-- fb_setup: the app secret can be left null to reuse the saved one.
create or replace function public.fb_setup(p_user_token text, p_app_secret text) returns text
language plpgsql security definer set search_path = public as $$
declare v_req bigint; v_secret text;
begin
  v_secret := coalesce(nullif(trim(p_app_secret), ''), public._fb_secret('fb_app_secret'));
  if v_secret is null then return 'no app secret saved -- pass it as the second value'; end if;
  perform public._fb_put_secret('fb_app_secret', v_secret);
  v_req := net.http_get(
    url := 'https://graph.facebook.com/v25.0/oauth/access_token',
    params := jsonb_build_object('grant_type', 'fb_exchange_token', 'client_id', '1139798711980377',
                                 'client_secret', v_secret, 'fb_exchange_token', trim(p_user_token)),
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
  if v_state not in ('exchanging', 'listing', 'instagram') then
    perform cron.unschedule(jobid) from cron.job where jobname = 'fb-setup';
    return;
  end if;
  select * into r from net._http_response where id = v_req;
  if not found then return; end if;
  v_json := case when r.content ~ '^\s*\{' then r.content::jsonb else '{}'::jsonb end;
  if v_json ? 'error' or r.status_code <> 200 then
    perform public._fb_set('setup', 'error: ' || coalesce(v_json #>> '{error,message}', r.error_msg, 'HTTP ' || r.status_code));
    perform cron.unschedule(jobid) from cron.job where jobname = 'fb-setup';
    return;
  end if;
  if v_state = 'exchanging' then
    v_new := net.http_get(url := 'https://graph.facebook.com/v25.0/me/accounts',
      params := jsonb_build_object('fields', 'id,name,access_token', 'access_token', v_json ->> 'access_token'),
      timeout_milliseconds := 20000);
    perform public._fb_set('setup', 'listing');
    perform public._fb_set('setup_req', v_new::text);
  elsif v_state = 'listing' then
    select p into v_page from jsonb_array_elements(v_json -> 'data') p
      where p ->> 'name' ilike 'Rain Or Shows%' limit 1;
    if v_page is null then
      perform public._fb_set('setup', 'error: the key has no access to the Rain Or Shows Page -- tick it in the popup');
      return;
    end if;
    perform public._fb_put_secret('fb_page_token', v_page ->> 'access_token');
    perform public._fb_set('page_id', v_page ->> 'id');
    v_new := net.http_get(url := 'https://graph.facebook.com/v25.0/' || (v_page ->> 'id'),
      params := jsonb_build_object('fields', 'instagram_business_account', 'access_token', v_page ->> 'access_token'),
      timeout_milliseconds := 20000);
    perform public._fb_set('setup', 'instagram');
    perform public._fb_set('setup_req', v_new::text);
  else
    if v_json #>> '{instagram_business_account,id}' is not null then
      perform public._fb_set('ig_user_id', v_json #>> '{instagram_business_account,id}');
      perform public._fb_set('setup', 'done: Rain Or Shows (page ' || public._fb_get('page_id')
                                      || ', instagram ' || (v_json #>> '{instagram_business_account,id}') || ')');
    else
      perform public._fb_set('setup', 'done: Rain Or Shows (page ' || public._fb_get('page_id')
                                      || ') -- no Instagram account linked to the Page');
    end if;
    perform cron.unschedule(jobid) from cron.job where jobname = 'fb-setup';
  end if;
end; $$;
revoke all on function public.fb_setup_step() from public, anon, authenticated;

-- Keep the picture URL when the Facebook tick reads posts.json.
create or replace function public._fb_tonight_image() returns trigger
language plpgsql security definer set search_path = public as $$
declare r record; v_post jsonb;
begin
  if new.status = 'ready' and old.status = 'fetching' and new.image is null then
    select * into r from net._http_response where id = new.fetch_req;
    if found and r.content ~ '^\s*\{' then
      select p into v_post from jsonb_array_elements(r.content::jsonb -> 'posts') p
        where p ->> 'date' = new.day::text limit 1;
      new.image := v_post ->> 'image';
      new.ig_message := v_post ->> 'ig_message';
    end if;
  end if;
  return new;
end; $$;
drop trigger if exists fb_tonight_image on public.fb_tonight;
create trigger fb_tonight_image before update on public.fb_tonight
  for each row execute function public._fb_tonight_image();

create or replace function public.ig_tonight_tick() returns void
language plpgsql security definer set search_path = public as $$
declare
  v_now  timestamp := now() at time zone 'America/Los_Angeles';
  v_day  date := v_now::date;
  v_mins int := extract(hour from v_now)::int * 60 + extract(minute from v_now)::int;
  v_token text := public._fb_secret('fb_page_token');
  v_ig   text := public._fb_get('ig_user_id');
  v_row  public.fb_tonight;
  r record; v_json jsonb; v_caption text;
begin
  if v_mins < 12 * 60 or v_mins >= 14 * 60 or v_token is null or v_ig is null then return; end if;
  select * into v_row from public.fb_tonight where day = v_day;
  if not found or coalesce(v_row.ig_message, v_row.message) is null or v_row.image is null then return; end if;
  if v_row.ig_status in ('posted', 'failed') then return; end if;

  if (v_mins >= 13 * 60 or v_row.ig_tries >= 4) and not v_row.ig_alerted then
    update public.fb_tonight set ig_alerted = true, ig_status = 'failed' where day = v_day;
    perform public._fb_alert('Instagram TONIGHT post did NOT go up (' || v_day || ')',
      'Today''s Instagram post failed: ' || coalesce(v_row.ig_note, 'no reason given') || E'\n\n'
      || 'Picture: ' || v_row.image || E'\nCaption: ' || coalesce(v_row.ig_message, v_row.message));
    return;
  end if;

  if v_row.ig_status is null then
    v_caption := coalesce(v_row.ig_message, v_row.message) || E'\n\nTickets + every Portland show: link in bio → rainorshows.com'
                 || E'\n\n#portlandmusic #pdxmusic #livemusic #portlandoregon #pdx';
    update public.fb_tonight set ig_status = 'container', ig_tries = ig_tries + 1,
      ig_req = net.http_post(url := 'https://graph.facebook.com/v25.0/' || v_ig || '/media',
        body := jsonb_build_object('image_url', v_row.image, 'caption', v_caption, 'access_token', v_token),
        timeout_milliseconds := 30000)
      where day = v_day;
    return;
  end if;

  select * into r from net._http_response where id = v_row.ig_req;
  if not found then return; end if;
  v_json := case when r.content ~ '^\s*\{' then r.content::jsonb else '{}'::jsonb end;
  if not (v_json ? 'id') then
    update public.fb_tonight set ig_status = null,
      ig_note = coalesce(v_json #>> '{error,message}', r.error_msg, 'HTTP ' || r.status_code) where day = v_day;
    return;
  end if;

  if v_row.ig_status = 'container' then
    update public.fb_tonight set ig_status = 'publishing', ig_container = v_json ->> 'id',
      ig_req = net.http_post(url := 'https://graph.facebook.com/v25.0/' || v_ig || '/media_publish',
        body := jsonb_build_object('creation_id', v_json ->> 'id', 'access_token', v_token),
        timeout_milliseconds := 30000)
      where day = v_day;
  elsif v_row.ig_status = 'publishing' then
    update public.fb_tonight set ig_status = 'posted', ig_media = v_json ->> 'id', ig_note = null where day = v_day;
  end if;
end; $$;
revoke all on function public.ig_tonight_tick() from public, anon, authenticated;

select cron.unschedule(jobid) from cron.job where jobname = 'ig-tonight';
select cron.schedule('ig-tonight', '*/5 * * * *', 'select public.ig_tonight_tick()');
