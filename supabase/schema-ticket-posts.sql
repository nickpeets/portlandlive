-- PortlandLive — Fork Stage 3: ticket exchange posts
--
-- Run this once, in full, in the Supabase SQL Editor (Dashboard -> SQL Editor
-- -> New query -> paste -> Run). Like Stage 1 and Stage 2 it needs privileges
-- the anon key does not have (SECURITY DEFINER function, table grants), so it
-- cannot be applied from client-side code.
--
-- Depends on Stage 1: public.profiles must already exist.
--
-- Scope: post a spare, browse spares for one show, cancel your own post.
-- Deliberately NOT here: reputation counters, "handoff complete" state,
-- resale/affiliate links, and any free-text note on a post. Trade-scoped
-- messaging is Stage 4 and is where any back-and-forth belongs; a note field
-- now would become the de facto messaging channel and then have to be undone.

create table if not exists public.ticket_posts (
  id uuid primary key default gen_random_uuid(),

  -- Same non-FK pattern as comments.show_slug: shows live in shows.json /
  -- archive.json, so there is no shows table to reference.
  show_slug text not null,

  user_id uuid not null references auth.users (id) on delete cascade,

  -- Denormalized and server-derived, exactly as in comments. Never trusted
  -- from the client -- see set_ticket_post_display_name below.
  display_name text not null,

  -- The entire face-value-or-free guarantee is this column plus the two-option
  -- form that feeds it. There is no price column and no price input anywhere:
  -- a poster cannot express an amount, so there is nothing to police.
  price_type text not null,

  quantity integer not null,

  created_at timestamptz not null default now(),

  constraint ticket_posts_price_type_valid check (
    price_type in ('face_value', 'free')
  ),
  -- 8 is the cap: enough for a group of friends who bought together, low
  -- enough that a bulk reseller cannot use this as a storefront.
  constraint ticket_posts_quantity_range check (
    quantity between 1 and 8
  ),
  constraint ticket_posts_show_slug_length check (
    char_length(show_slug) between 1 and 200
  ),
  constraint ticket_posts_display_name_length check (
    char_length(trim(display_name)) between 1 and 60
  )
);

-- Every read is "the spare posts for one show, newest first".
create index if not exists ticket_posts_show_slug_created_at_idx
  on public.ticket_posts (show_slug, created_at desc);

-- Identical in shape and intent to Stage 2's set_comment_display_name: the
-- client sends only show_slug, price_type and quantity. Identity is derived
-- here, so a signed-in user cannot post a spare under someone else's name --
-- RLS alone would not catch that, since the forged row would still be theirs.
create or replace function public.set_ticket_post_display_name()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  new.user_id := auth.uid();
  select p.display_name into new.display_name
    from public.profiles p
   where p.id = new.user_id;
  if new.display_name is null then
    raise exception 'no profile row for %', new.user_id
      using errcode = 'foreign_key_violation';
  end if;
  return new;
end;
$$;

drop trigger if exists ticket_posts_set_display_name on public.ticket_posts;

create trigger ticket_posts_set_display_name
  before insert on public.ticket_posts
  for each row execute function public.set_ticket_post_display_name();

alter table public.ticket_posts enable row level security;

drop policy if exists ticket_posts_select_all on public.ticket_posts;
drop policy if exists ticket_posts_insert_own on public.ticket_posts;
drop policy if exists ticket_posts_delete_own on public.ticket_posts;

-- "Two spares going at face value" is public listings information, the same
-- category as the listing itself and as comments. Readable logged out.
create policy ticket_posts_select_all
  on public.ticket_posts
  for select
  to anon, authenticated
  using (true);

create policy ticket_posts_insert_own
  on public.ticket_posts
  for insert
  to authenticated
  with check (user_id = auth.uid());

-- Canceling a post is deleting it.
create policy ticket_posts_delete_own
  on public.ticket_posts
  for delete
  to authenticated
  using (user_id = auth.uid());

-- No UPDATE policy, deliberately: a post is not editable. Changing quantity
-- means cancel and repost, which keeps created_at honest about when the
-- current offer appeared.

grant select on public.ticket_posts to anon;
grant select, insert, delete on public.ticket_posts to authenticated;
