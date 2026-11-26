-- ============================================================================
-- Miracle alerts (Nov 25 2026).
--
-- Nick: whenever someone posts a miracle, every Rain Or Shows account holder
-- gets an email, and the email links to that show's page.
--
-- Sent as a Resend BROADCAST, not through /emails, so it doesn't count
-- against the free plan's 100/day transactional cap (sign-in, DM and follow
-- emails keep that to themselves). Free marketing tier: up to 1,000 contacts.
--
-- Pieces:
--   1. resend_contact_queue  -- every member is mirrored into the Resend
--      segment "Members". New sign-ups are queued by a trigger; existing
--      members are backfilled. A cron job drains 8 rows a minute.
--   2. miracle_alerts        -- one row per show that gets an alert.
--   3. miracle_alert_sweep() -- every 5 minutes: finds miracles that are
--      10+ minutes old (giver didn't cancel), and broadcasts.
--
-- Guardrails (anyone signed in can post a miracle, and this mails everyone):
--   * one alert per show, ever
--   * at most 3 alerts per Pacific day, site-wide
--   * the giver's account must be at least 24 hours old
--   * the show date (from the slug) must be today or later
--   * 10-minute wait, so a post that gets cancelled never mails anyone
--
-- Vault secrets used:
--   resend_full_key         -- a Resend key with FULL access (contacts and
--                              broadcasts need it; the site's other key is
--                              sending-only). Falls back to resend_api_key.
--   resend_members_segment  -- the "Members" segment id.
--
-- Run once, in full, in the Supabase SQL Editor. Re-running is safe.
-- ============================================================================

create extension if not exists pg_net with schema extensions;
create extension if not exists pg_cron;

alter table public.ticket_posts add column if not exists show_title text;
alter table public.ticket_posts add column if not exists show_venue text;
alter table public.ticket_posts drop constraint if exists ticket_posts_show_title_len;
alter table public.ticket_posts add constraint ticket_posts_show_title_len
  check (show_title is null or char_length(show_title) <= 160) not valid;
alter table public.ticket_posts drop constraint if exists ticket_posts_show_venue_len;
alter table public.ticket_posts add constraint ticket_posts_show_venue_len
  check (show_venue is null or char_length(show_venue) <= 80) not valid;

-- One Resend call. Returns the pg_net request id (null if no key / failure).
create or replace function public._ros_resend(p_method text, p_path text, p_body jsonb default null)
returns bigint language plpgsql security definer set search_path = public as $$
declare v_key text; v_hdr jsonb; v_id bigint;
begin
  select decrypted_secret into v_key from vault.decrypted_secrets where name = 'resend_full_key' limit 1;
  if v_key is null then
    select decrypted_secret into v_key from vault.decrypted_secrets where name = 'resend_api_key' limit 1;
  end if;
  if v_key is null then return null; end if;
  v_hdr := jsonb_build_object('Authorization', 'Bearer ' || trim(v_key), 'Content-Type', 'application/json');
  begin
    if p_method = 'DELETE' then
      select net.http_delete(url := 'https://api.resend.com' || p_path, headers := v_hdr) into v_id;
    else
      select net.http_post(url := 'https://api.resend.com' || p_path, headers := v_hdr,
                           body := coalesce(p_body, '{}'::jsonb)) into v_id;
    end if;
  exception when others then return null;  -- a failed call never stops a sweep
  end;
  return v_id;
end; $$;
revoke all on function public._ros_resend(text, text, jsonb) from public, anon, authenticated;

-- 1. Members -> Resend contacts
create table if not exists public.resend_contact_queue (
  id bigserial primary key,
  email text not null,
  action text not null check (action in ('add', 'remove')),
  queued_at timestamptz not null default now(),
  sent_at timestamptz,
  request_id bigint
);
alter table public.resend_contact_queue enable row level security;
revoke all on public.resend_contact_queue from anon, authenticated;
create index if not exists resend_contact_queue_pending_idx
  on public.resend_contact_queue (id) where sent_at is null;

create or replace function public.resend_contact_enqueue()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' and coalesce(new.email, '') <> '' then
    insert into public.resend_contact_queue (email, action) values (lower(new.email), 'add');
  elsif tg_op = 'UPDATE' and coalesce(new.email, '') <> '' and new.email is distinct from old.email then
    if coalesce(old.email, '') <> '' then
      insert into public.resend_contact_queue (email, action) values (lower(old.email), 'remove');
    end if;
    insert into public.resend_contact_queue (email, action) values (lower(new.email), 'add');
  elsif tg_op = 'DELETE' and coalesce(old.email, '') <> '' then
    insert into public.resend_contact_queue (email, action) values (lower(old.email), 'remove');
  end if;
  return null;
exception when others then return null;  -- never block a sign-up
end; $$;

drop trigger if exists ros_resend_contact_sync on auth.users;
create trigger ros_resend_contact_sync
  after insert or update of email or delete on auth.users
  for each row execute function public.resend_contact_enqueue();

create or replace function public.resend_contact_drain()
returns integer language plpgsql security definer set search_path = public as $$
declare r record; v_seg text; n integer := 0;
begin
  select decrypted_secret into v_seg from vault.decrypted_secrets where name = 'resend_members_segment' limit 1;
  if v_seg is null then return 0; end if;
  for r in select * from public.resend_contact_queue where sent_at is null order by id limit 8 for update skip locked
  loop
    update public.resend_contact_queue
       set sent_at = now(),
           request_id = case r.action
             when 'add' then public._ros_resend('POST', '/contacts',
               jsonb_build_object('email', r.email, 'unsubscribed', false,
                                  'segments', jsonb_build_array(jsonb_build_object('id', trim(v_seg)))))
             else public._ros_resend('DELETE', '/contacts/' || r.email) end
     where id = r.id;
    n := n + 1;
  end loop;
  return n;
end; $$;
revoke all on function public.resend_contact_drain() from public, anon, authenticated;

insert into public.resend_contact_queue (email, action)
select lower(u.email), 'add'
  from auth.users u
 where coalesce(u.email, '') <> ''
   and not exists (select 1 from public.resend_contact_queue q where q.email = lower(u.email));

select cron.unschedule(jobid) from cron.job where jobname = 'resend-contact-drain';
select cron.schedule('resend-contact-drain', '* * * * *', 'select public.resend_contact_drain()');

-- 2 + 3. Miracle -> broadcast
create table if not exists public.miracle_alerts (
  show_slug text primary key,
  ticket_post_id uuid,
  sent_at timestamptz not null default now(),
  request_id bigint
);
alter table public.miracle_alerts enable row level security;
revoke all on public.miracle_alerts from anon, authenticated;

create or replace function public._ros_esc(t text)
returns text language sql immutable as $$
  select replace(replace(replace(replace(coalesce(t, ''), '&', '&amp;'), '<', '&lt;'), '>', '&gt;'), '"', '&quot;');
$$;

create or replace function public._ros_slug_date(p_slug text)
returns date language plpgsql immutable as $$
begin
  if p_slug !~ '^\d{4}-\d{2}-\d{2}-' then return null; end if;
  return left(p_slug, 10)::date;
exception when others then return null;
end; $$;

create or replace function public.miracle_alert_sweep()
returns integer language plpgsql security definer set search_path = public as $$
declare
  r record; v_seg text; v_today date; v_sent_today integer;
  v_title text; v_venue text; v_when text; v_url text; v_subj text; v_html text; v_n integer := 0;
begin
  select decrypted_secret into v_seg from vault.decrypted_secrets where name = 'resend_members_segment' limit 1;
  if v_seg is null then return 0; end if;
  v_today := (now() at time zone 'America/Los_Angeles')::date;

  for r in
    select distinct on (p.show_slug) p.*
      from public.ticket_posts p
      join auth.users u on u.id = p.user_id
     where p.price_type = 'free'
       and p.created_at <= now() - interval '10 minutes'
       and p.created_at >  now() - interval '24 hours'
       and u.created_at <= p.created_at - interval '24 hours'
       and public._ros_slug_date(p.show_slug) >= v_today
       and not exists (select 1 from public.miracle_alerts a where a.show_slug = p.show_slug)
     order by p.show_slug, p.created_at
  loop
    select count(*) into v_sent_today from public.miracle_alerts
     where (sent_at at time zone 'America/Los_Angeles')::date = v_today;
    exit when v_sent_today >= 3;

    v_title := nullif(trim(r.show_title), '');
    v_venue := nullif(trim(r.show_venue), '');
    v_when  := to_char(public._ros_slug_date(r.show_slug), 'FMDay, Mon FMDD');
    v_url   := 'https://rainorshows.com/show/' || r.show_slug || '/?ref=miracle-email';
    v_subj  := 'A miracle on Rain Or Shows: free tickets' || coalesce(' to ' || v_title, '');
    v_html  :=
      '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#222;max-width:560px">'
      || '<p style="display:inline-block;background:#e3b23c;color:#3a2a10;font-weight:700;padding:4px 12px;border-radius:999px;margin:0 0 14px">&#10024; A miracle</p>'
      || '<p style="margin:0 0 6px">Someone on Rain Or Shows is giving away '
      || case when r.quantity = 1 then 'a free ticket' else r.quantity || ' free tickets' end || '.</p>'
      || coalesce('<p style="font-size:20px;font-weight:700;margin:10px 0 2px">' || _ros_esc(v_title) || '</p>', '')
      || '<p style="margin:0 0 18px;color:#555">' || coalesce(_ros_esc(v_venue) || ' &middot; ', '') || v_when || '</p>'
      || '<p style="margin:0 0 18px"><a href="' || v_url || '" '
      || 'style="background:#b5562b;color:#fff;text-decoration:none;padding:10px 18px;border-radius:999px;display:inline-block">See the miracle</a></p>'
      || '<p>First to message the giver usually gets them.</p>'
      || '<p style="font-size:12px;color:#999;margin-top:28px">You''re getting this because you have a Rain Or Shows account. '
      || '<a href="{{{RESEND_UNSUBSCRIBE_URL}}}" style="color:#999">Unsubscribe</a><br>'
      || 'Rain Or Shows &middot; 4822 SW Scholls Ferry Rd, Portland, OR 97225</p></div>';

    insert into public.miracle_alerts (show_slug, ticket_post_id, request_id)
    values (r.show_slug, r.id,
            public._ros_resend('POST', '/broadcasts', jsonb_build_object(
              'segment_id', trim(v_seg),
              'from', 'Rain Or Shows <noreply@rainorshows.com>',
              'subject', v_subj,
              'html', v_html,
              'name', 'Miracle: ' || r.show_slug,
              'send', true)));
    v_n := v_n + 1;
  end loop;
  return v_n;
end; $$;
revoke all on function public.miracle_alert_sweep() from public, anon, authenticated;

select cron.unschedule(jobid) from cron.job where jobname = 'miracle-alert-sweep';
select cron.schedule('miracle-alert-sweep', '*/5 * * * *', 'select public.miracle_alert_sweep()');

select jobname, schedule from cron.job where jobname in ('resend-contact-drain', 'miracle-alert-sweep');
