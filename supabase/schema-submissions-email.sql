-- ============================================================================
-- Submissions line, part 2: review by email.
--
-- Nick reviews from his inbox, not from a moderation page. Each submission
-- gets a secret token; the notification email carries Approve / Reject links
-- built from it; tapping one hits a public RPC that checks the token and
-- sets the status. No sign-in. The token is a random uuid -- unguessable --
-- and is never exposed anywhere but that one email.
--
-- Sending uses pg_net (Supabase's async HTTP extension) from an AFTER INSERT
-- trigger, straight to Resend's API. No edge function to deploy. The Resend
-- key lives in Supabase Vault and is read only by the trigger function.
--
-- Apply in the SQL Editor AFTER schema-submissions.sql. Then store the key:
--   select vault.create_secret('re_xxxxxxxx', 'resend_api_key');
-- ============================================================================

create extension if not exists pg_net with schema extensions;

alter table public.show_submissions
  add column if not exists review_token uuid not null default gen_random_uuid();


-- ----------------------------------------------------------------------------
-- review_by_token: the Approve / Reject link target. PUBLIC, because the
-- token is the credential. Idempotent: tapping Approve twice is fine, and a
-- second tap after the other button reports what happened.
-- ----------------------------------------------------------------------------
create or replace function public.review_by_token(
  p_id uuid, p_token uuid, p_action text
)
returns table (ok boolean, status text, title text, venue text, "date" text)
language plpgsql
security definer
set search_path = public
as $$
declare
  r public.show_submissions%rowtype;
begin
  if p_action not in ('approved', 'rejected') then
    raise exception 'action must be approved or rejected';
  end if;
  select * into r from public.show_submissions s
   where s.id = p_id and s.review_token = p_token;
  if not found then
    -- Wrong id or wrong token. Say nothing useful.
    return query select false, null::text, null::text, null::text, null::text;
    return;
  end if;
  update public.show_submissions
     set status = p_action, reviewed_at = now(),
         review_note = coalesce(review_note, 'reviewed by email link')
   where id = p_id;
  return query
    select true, p_action, r.title, r.venue, to_char(r."date", 'FMDay, Mon FMDD');
end;
$$;

revoke all on function public.review_by_token(uuid, uuid, text) from public;
grant execute on function public.review_by_token(uuid, uuid, text) to anon, authenticated;


-- ----------------------------------------------------------------------------
-- notify_submission: AFTER INSERT trigger. Builds the email and hands it to
-- pg_net, which sends it asynchronously; the insert never waits on Resend
-- and never fails because of it.
-- ----------------------------------------------------------------------------
create or replace function public.notify_submission()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_key   text;
  v_base  text := 'https://rainorshows.com/#/review/';
  v_ok    text;
  v_no    text;
  v_html  text;
  v_subj  text;
  esc     text;
begin
  select decrypted_secret into v_key
    from vault.decrypted_secrets where name = 'resend_api_key' limit 1;
  if v_key is null then
    -- No key stored: the submission still lands in the table, it just
    -- doesn't email. Visible in submission_queue().
    return new;
  end if;

  v_ok := v_base || new.id || '/' || new.review_token || '/approved';
  v_no := v_base || new.id || '/' || new.review_token || '/rejected';
  v_subj := '[ROS] New show: ' || new.title || ' @ ' || new.venue
            || ' -- ' || to_char(new."date", 'Mon FMDD');

  -- Plain HTML, no styling to speak of; it has to survive every mail client.
  v_html :=
    '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#222;max-width:560px">'
    || '<p style="font-size:13px;color:#777;margin:0 0 12px">A show was submitted to Rain Or Shows.</p>'
    || '<p style="font-size:20px;font-weight:600;margin:0 0 4px">' || replace(replace(new.title,'<','&lt;'),'>','&gt;') || '</p>'
    || '<p style="margin:0 0 14px">' || replace(replace(new.venue,'<','&lt;'),'>','&gt;')
    || ' &middot; ' || to_char(new."date", 'FMDay, Month FMDD, YYYY')
    || coalesce(' &middot; ' || new."time", '') || '</p>'
    || '<table style="font-size:14px;border-collapse:collapse">'
    || case when new.url is not null then '<tr><td style="color:#777;padding:2px 12px 2px 0">Link</td><td><a href="' || replace(new.url,'"','') || '">' || replace(replace(new.url,'<','&lt;'),'>','&gt;') || '</a></td></tr>' else '' end
    || case when new.age is not null then '<tr><td style="color:#777;padding:2px 12px 2px 0">Age</td><td>' || new.age || '</td></tr>' else '' end
    || case when new.neighborhood is not null then '<tr><td style="color:#777;padding:2px 12px 2px 0">Area</td><td>' || replace(replace(new.neighborhood,'<','&lt;'),'>','&gt;') || '</td></tr>' else '' end
    || case when new.address is not null then '<tr><td style="color:#777;padding:2px 12px 2px 0">Address</td><td>' || replace(replace(new.address,'<','&lt;'),'>','&gt;') || '</td></tr>' else '' end
    || case when new.notes is not null then '<tr><td style="color:#777;padding:2px 12px 2px 0;vertical-align:top">Notes</td><td>' || replace(replace(new.notes,'<','&lt;'),'>','&gt;') || '</td></tr>' else '' end
    || '<tr><td style="color:#777;padding:2px 12px 2px 0">From</td><td>' || replace(replace(new.submitter_email,'<','&lt;'),'>','&gt;') || '</td></tr>'
    || '</table>'
    || '<p style="margin:22px 0 0">'
    || '<a href="' || v_ok || '" style="display:inline-block;background:#2f5a4a;color:#f3ead7;text-decoration:none;font-weight:600;padding:11px 20px;border-radius:6px;margin-right:10px">Approve</a>'
    || '<a href="' || v_no || '" style="display:inline-block;background:#f3ead7;color:#2f5a4a;text-decoration:none;font-weight:600;padding:11px 20px;border-radius:6px;border:1px solid #2f5a4a">Reject</a>'
    || '</p>'
    || '<p style="font-size:12px;color:#999;margin:22px 0 0">One tap either way. Approved shows appear on the site at the next nightly build (about 7am Pacific). These links only work for this submission.</p>'
    || '</div>';

  perform net.http_post(
    url     := 'https://api.resend.com/emails',
    headers := jsonb_build_object(
                 'Authorization', 'Bearer ' || v_key,
                 'Content-Type', 'application/json'),
    body    := jsonb_build_object(
                 'from', 'Rain Or Shows <noreply@rainorshows.com>',
                 -- Straight to Gmail, not via the nick@rainorshows.com forwarder:
                 -- Porkbun's forward held the second-ever notification for
                 -- 7+ minutes while Resend showed "Sent" with no delivery.
                 'to',   jsonb_build_array('nickpeets@gmail.com'),
                 'reply_to', new.submitter_email,
                 'subject', v_subj,
                 'html', v_html)
  );
  return new;
exception when others then
  -- Never let the email path break the insert.
  return new;
end;
$$;

drop trigger if exists show_submissions_notify on public.show_submissions;
create trigger show_submissions_notify
  after insert on public.show_submissions
  for each row execute function public.notify_submission();
