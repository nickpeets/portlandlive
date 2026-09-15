-- ============================================================================
-- Show submissions -- the "submissions line".
--
-- Why. Rain Or Shows never scraped Facebook or Instagram, and a growing share
-- of Portland's small rooms post only there (Kenton Club until they typed
-- their calendar into their homepage; most bars). The scraper has reached the
-- venues it can reach. The alt-weekly listings page it descends from never
-- scraped either -- it had a phone number and an address to send your show
-- to. This is that.
--
-- Shape.
--   * Anyone can submit, signed in or not. One RPC, validated, rate-limited
--     by email so a bad actor cannot flood the queue.
--   * Only moderators can see the queue, approve, or reject.
--   * Approved rows are served by a PUBLIC RPC in the feed's own 8-field
--     shape, so build_shows.py pulls them with the anon key -- no secret in
--     CI, and no code commit to add a show. Rejected and pending rows never
--     leave the table.
--
-- Apply in the Supabase SQL Editor. Idempotent.
-- ============================================================================

create table if not exists public.show_submissions (
  id              uuid primary key default gen_random_uuid(),
  created_at      timestamptz not null default now(),
  -- the show, in the feed's vocabulary
  title           text not null,
  venue           text not null,
  neighborhood    text,
  address         text,
  date            date not null,
  time            text,                      -- "8:00 PM" or empty, same as the feed
  url             text,                      -- event or ticket page
  age             text check (age is null or age in ('all-ages', '21+', '18+')),
  notes           text,                      -- submitter's note to the reviewer, never published
  -- who sent it
  submitter_email text not null,
  submitter_id    uuid references auth.users (id) on delete set null,
  -- review
  status          text not null default 'pending'
                  check (status in ('pending', 'approved', 'rejected')),
  reviewed_at     timestamptz,
  reviewed_by     uuid references auth.users (id) on delete set null,
  review_note     text
);

create index if not exists show_submissions_status_idx
  on public.show_submissions (status, created_at desc);
create index if not exists show_submissions_email_recent_idx
  on public.show_submissions (submitter_email, created_at desc);

alter table public.show_submissions enable row level security;

-- Nobody touches the table directly. All access is through the RPCs below,
-- which are SECURITY DEFINER and enforce their own rules. No policies means
-- no direct SELECT/INSERT/UPDATE for anon or authenticated.
revoke all on public.show_submissions from anon, authenticated;


-- ----------------------------------------------------------------------------
-- submit_show: the public front door.
--
-- Validates every field, rate-limits by email (5 per hour, 20 per day), and
-- inserts as pending. Returns the new id. Raises on anything invalid, with a
-- message the form can show verbatim.
-- ----------------------------------------------------------------------------
create or replace function public.submit_show(
  p_title    text,
  p_venue    text,
  p_date     date,
  p_time     text default null,
  p_url      text default null,
  p_age      text default null,
  p_notes    text default null,
  p_email    text default null,
  p_neighborhood text default null,
  p_address  text default null
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_email  text := lower(trim(coalesce(p_email, '')));
  v_title  text := trim(coalesce(p_title, ''));
  v_venue  text := trim(coalesce(p_venue, ''));
  v_time   text := trim(coalesce(p_time, ''));
  v_url    text := trim(coalesce(p_url, ''));
  v_age    text := nullif(trim(coalesce(p_age, '')), '');
  v_id     uuid;
  v_hour   int;
  v_day    int;
begin
  -- Field validation. Messages are user-facing.
  if v_title = '' or length(v_title) > 160 then
    raise exception 'Enter a show title (up to 160 characters).';
  end if;
  if v_venue = '' or length(v_venue) > 80 then
    raise exception 'Enter a venue name (up to 80 characters).';
  end if;
  if p_date is null then
    raise exception 'Enter a date.';
  end if;
  if p_date < current_date then
    raise exception 'That date has already passed.';
  end if;
  if p_date > current_date + interval '365 days' then
    raise exception 'Enter a date within the next year.';
  end if;
  if v_time <> '' and v_time !~* '^\d{1,2}(:\d{2})?\s*[ap]m$' then
    raise exception 'Enter the time like 8:00 PM, or leave it blank.';
  end if;
  if v_url <> '' and (length(v_url) > 500 or v_url !~* '^https?://') then
    raise exception 'Enter a full link starting with http, or leave it blank.';
  end if;
  if v_age is not null and v_age not in ('all-ages', '21+', '18+') then
    raise exception 'Age must be all-ages, 21+, or 18+.';
  end if;
  if length(coalesce(p_notes, '')) > 1000 then
    raise exception 'Notes can be up to 1000 characters.';
  end if;
  if v_email = '' or length(v_email) > 254 or v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then
    raise exception 'Enter an email address so we can follow up if needed.';
  end if;

  -- Rate limit by email. A signed-in user's own address counts the same.
  select count(*) into v_hour from public.show_submissions
   where submitter_email = v_email and created_at > now() - interval '1 hour';
  select count(*) into v_day from public.show_submissions
   where submitter_email = v_email and created_at > now() - interval '1 day';
  if v_hour >= 5 or v_day >= 20 then
    raise exception 'That''s a lot of submissions at once. Try again in a bit.';
  end if;

  insert into public.show_submissions
    (title, venue, neighborhood, address, date, time, url, age, notes,
     submitter_email, submitter_id)
  values
    (v_title, v_venue, nullif(trim(coalesce(p_neighborhood, '')), ''),
     nullif(trim(coalesce(p_address, '')), ''), p_date,
     nullif(v_time, ''), nullif(v_url, ''), v_age,
     nullif(trim(coalesce(p_notes, '')), ''), v_email, auth.uid())
  returning id into v_id;
  return v_id;
end;
$$;

revoke all on function public.submit_show(text, text, date, text, text, text, text, text, text, text) from public;
grant execute on function public.submit_show(text, text, date, text, text, text, text, text, text, text) to anon, authenticated;


-- ----------------------------------------------------------------------------
-- submission_queue: what moderators see. Pending first, newest first.
-- Returns nothing for anyone else -- same pattern as report_queue.
-- ----------------------------------------------------------------------------
create or replace function public.submission_queue(p_status text default 'pending')
returns table (
  id uuid, created_at timestamptz,
  title text, venue text, neighborhood text, address text,
  "date" date, "time" text, url text, age text, notes text,
  submitter_email text, submitter_id uuid,
  status text, reviewed_at timestamptz, review_note text
)
language sql
stable
security definer
set search_path = public
as $$
  select s.id, s.created_at,
         s.title, s.venue, s.neighborhood, s.address,
         s.date, s.time, s.url, s.age, s.notes,
         s.submitter_email, s.submitter_id,
         s.status, s.reviewed_at, s.review_note
    from public.show_submissions s
   where public.is_moderator()
     and (p_status is null or s.status = p_status)
   order by s.created_at desc
   limit 200
$$;

revoke all on function public.submission_queue(text) from public;
grant execute on function public.submission_queue(text) to authenticated;


-- ----------------------------------------------------------------------------
-- review_submission: approve or reject. Moderators only. A moderator may
-- also edit the fields on approval -- a submitter's "Dantes" becomes the
-- feed's "Dante's" -- so the corrected values are passed back in. Null means
-- keep what was submitted.
-- ----------------------------------------------------------------------------
create or replace function public.review_submission(
  p_id      uuid,
  p_status  text,
  p_note    text default null,
  p_title   text default null,
  p_venue   text default null,
  p_date    date default null,
  p_time    text default null,
  p_url     text default null,
  p_age     text default null,
  p_neighborhood text default null,
  p_address text default null
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if not public.is_moderator() then
    raise exception 'not a moderator';
  end if;
  if p_status not in ('approved', 'rejected', 'pending') then
    raise exception 'status must be approved, rejected, or pending';
  end if;
  update public.show_submissions
     set status       = p_status,
         reviewed_at  = now(),
         reviewed_by  = auth.uid(),
         review_note  = coalesce(p_note, review_note),
         title        = coalesce(nullif(trim(p_title), ''), title),
         venue        = coalesce(nullif(trim(p_venue), ''), venue),
         "date"       = coalesce(p_date, "date"),
         "time"       = coalesce(p_time, "time"),
         url          = coalesce(p_url, url),
         age          = coalesce(p_age, age),
         neighborhood = coalesce(p_neighborhood, neighborhood),
         address      = coalesce(p_address, address)
   where id = p_id;
  if not found then
    raise exception 'no such submission';
  end if;
end;
$$;

revoke all on function public.review_submission(uuid, text, text, text, text, date, text, text, text, text, text) from public;
grant execute on function public.review_submission(uuid, text, text, text, text, date, text, text, text, text, text) to authenticated;


-- ----------------------------------------------------------------------------
-- approved_submissions: the feed's view. PUBLIC. Returns approved rows from
-- yesterday forward, in the feed's own field names, so build_shows.py can
-- fetch it with the anon key and merge it like a hand-added row. Nothing
-- private is in it -- no email, no notes, no reviewer.
-- ----------------------------------------------------------------------------
create or replace function public.approved_submissions()
returns table (
  title text, venue text, neighborhood text, address text,
  "date" text, "time" text, "venueUrl" text, age text
)
language sql
stable
security definer
set search_path = public
as $$
  select s.title, s.venue,
         coalesce(s.neighborhood, ''), coalesce(s.address, ''),
         to_char(s.date, 'YYYY-MM-DD'),
         coalesce(s.time, ''), coalesce(s.url, ''), coalesce(s.age, '')
    from public.show_submissions s
   where s.status = 'approved'
     and s.date >= current_date - 1
   order by s.date, s.venue, s.title
$$;

revoke all on function public.approved_submissions() from public;
grant execute on function public.approved_submissions() to anon, authenticated;


-- ----------------------------------------------------------------------------
-- pending_submission_count: one number for the moderator badge. Zero for
-- non-moderators rather than an error, so the nav can call it freely.
-- ----------------------------------------------------------------------------
create or replace function public.pending_submission_count()
returns int
language sql
stable
security definer
set search_path = public
as $$
  select case when public.is_moderator()
              then (select count(*)::int from public.show_submissions where status = 'pending')
              else 0 end
$$;

revoke all on function public.pending_submission_count() from public;
grant execute on function public.pending_submission_count() to authenticated;
