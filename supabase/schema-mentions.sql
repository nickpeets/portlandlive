-- PortlandLive — Fork Stage 10, Part 3: @mentions in show comments
--
-- Run this once, in full, in the Supabase SQL Editor, BEFORE deploying the
-- matching index.html. Depends on Stage 2 (comments), schema-handles.sql
-- (profiles.handle) and schema-reporting.sql (content_reports, for the
-- hidden-comment rule in my_mentions).
--
-- Shape, and the reasons:
--
--   * comment_mentions stores (comment_id, user_id) -- ids, never names.
--     comments.display_name is a frozen snapshot by design; a text mention
--     would rot the first time someone used their one rename.
--   * Parsing happens HERE, in an after-insert trigger, not in the client. A
--     client-side cap is not a cap: the mention insert would be a second
--     round trip and RLS can check parentage of the comment, not whether the
--     body actually contains the handle. INSERT on comment_mentions is
--     granted to nobody; rows arrive by trigger and leave by cascade.
--   * The regex has both boundaries:
--       (^|[^A-Za-z0-9_])@([A-Za-z0-9_]{3,20})(?![A-Za-z0-9_])
--     Unanchored, @shakedownsteve_the_third would match its first 20 chars
--     and resolve to a DIFFERENT real user. The left guard stops
--     me@nickpeets parsing as a mention.
--   * Cap 5 rows per comment; the comment posts regardless. A six-name
--     comment gets five notifications, not an error about a limit the
--     author had no way to see.
--   * Unresolved @foo is plain text. Self-mentions do not notify.
--   * Resolution inside the trigger is a direct lookup on profiles, not
--     profile_by_handle(): that function is rate-limited and volatile, and
--     a trigger firing as definer is neither a client nor a guess. The
--     client uses profile_by_handle for everything it resolves itself.
--
-- Reads:
--   mentions_for_comments(uuid[])  which mentions in THESE comments resolved,
--                                  with the current handle, so the renderer
--                                  can turn exactly those tokens into links.
--                                  Public, like comments. Scoped to comment
--                                  ids the caller already has -- not a bulk
--                                  id -> handle mapper, which D3 forbids.
--   my_mentions(limit)             the caller's inbox rows. authenticated.
--
-- Re-running: safe.

create table if not exists public.comment_mentions (
  id uuid primary key default gen_random_uuid(),
  comment_id uuid not null references public.comments (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now(),
  constraint comment_mentions_comment_user_unique unique (comment_id, user_id)
);

-- The inbox read: "mentions of me, newest first".
create index if not exists comment_mentions_user_created_at_idx
  on public.comment_mentions (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Parser. Distinct handles in order of first appearance, case preserved
-- (compared lowercased by the callers). Pure, so it can be tested alone.
-- ---------------------------------------------------------------------------
create or replace function public.extract_mention_handles(p_body text)
returns text[]
language sql
immutable
as $$
  select coalesce(array_agg(h order by first_ord), '{}'::text[])
    from (
      select distinct on (lower(m[2])) m[2] as h, ord as first_ord
        from regexp_matches(coalesce(p_body, ''),
               '(^|[^A-Za-z0-9_])@([A-Za-z0-9_]{3,20})(?![A-Za-z0-9_])', 'g')
             with ordinality as t(m, ord)
       order by lower(m[2]), ord
    ) d;
$$;

revoke all on function public.extract_mention_handles(text) from public;

-- ---------------------------------------------------------------------------
-- The trigger
-- ---------------------------------------------------------------------------
create or replace function public.set_comment_mentions()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  h text;
  target uuid;
  n integer := 0;
begin
  foreach h in array public.extract_mention_handles(new.body) loop
    exit when n >= 5;
    select p.id into target
      from public.profiles p
     where lower(p.handle) = lower(h);
    if target is null or target = new.user_id then
      continue;
    end if;
    insert into public.comment_mentions (comment_id, user_id)
    values (new.id, target)
    on conflict (comment_id, user_id) do nothing;
    if found then
      n := n + 1;
    end if;
  end loop;
  return new;
end;
$$;

drop trigger if exists comments_set_mentions on public.comments;

create trigger comments_set_mentions
  after insert on public.comments
  for each row execute function public.set_comment_mentions();

-- ---------------------------------------------------------------------------
-- Access
-- ---------------------------------------------------------------------------
alter table public.comment_mentions enable row level security;

drop policy if exists comment_mentions_select_own on public.comment_mentions;

-- Your own mentions, for the inbox. Rendering other people's comments goes
-- through mentions_for_comments() below, so no wider policy is needed.
create policy comment_mentions_select_own
  on public.comment_mentions
  for select
  to authenticated
  using (user_id = auth.uid());

-- No INSERT, UPDATE or DELETE policy, and no such grant: the trigger writes,
-- the comment's cascade deletes.
grant select on public.comment_mentions to authenticated;

-- ---------------------------------------------------------------------------
-- Reads
-- ---------------------------------------------------------------------------
create or replace function public.mentions_for_comments(p_comment_ids uuid[])
returns table (comment_id uuid, user_id uuid, handle text)
language sql
security definer
set search_path = public
stable
as $$
  select m.comment_id, m.user_id, p.handle
    from public.comment_mentions m
    join public.profiles p on p.id = m.user_id
   where m.comment_id = any (coalesce(p_comment_ids, '{}'::uuid[]));
$$;

revoke all on function public.mentions_for_comments(uuid[]) from public;
grant execute on function public.mentions_for_comments(uuid[]) to anon, authenticated;

-- Hidden comments (reported, pending review) are excluded with the same
-- predicate hidden_targets() uses: a report hides immediately, and a
-- notification pointing at hidden text would be a way around that. An
-- upheld report deletes the comment, and the cascade removes the mention.
create or replace function public.my_mentions(p_limit integer default 50)
returns table (
  mention_id uuid, comment_id uuid, show_slug text, body text,
  author_id uuid, author_name text, created_at timestamptz
)
language sql
security definer
set search_path = public
stable
as $$
  select m.id, c.id, c.show_slug, c.body, c.user_id, c.display_name, m.created_at
    from public.comment_mentions m
    join public.comments c on c.id = m.comment_id
   where m.user_id = auth.uid()
     and not exists (
       select 1 from public.content_reports r
        where r.target_type = 'comment'
          and r.target_id = c.id
          and (r.status is null or r.status = 'upheld')
     )
   order by m.created_at desc
   limit greatest(1, least(coalesce(p_limit, 50), 200));
$$;

revoke all on function public.my_mentions(integer) from public;
grant execute on function public.my_mentions(integer) to authenticated;
