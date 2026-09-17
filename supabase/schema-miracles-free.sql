-- Miracles are free only (decided Sep 17 2026).
--
-- A miracle, in the Deadhead sense the feature is named for, is a gift. The
-- post form no longer offers "At face value"; this constraint makes the
-- database refuse a face-value post from anything else, too.
--
-- NOT VALID: posts made before today keep the price_type they were posted
-- with. Postgres still enforces the rule on every new insert. Those older
-- posts drop out of the listing on their own once their show passes.
-- The original ticket_posts_price_type_valid constraint stays in place.
--
-- Run once, in full, in the Supabase SQL Editor.

alter table public.ticket_posts
  alter column price_type set default 'free';

alter table public.ticket_posts
  drop constraint if exists ticket_posts_free_only;

alter table public.ticket_posts
  add constraint ticket_posts_free_only check (price_type = 'free') not valid;

-- Check: the open face-value posts that predate the rule (informational).
select tp.created_at, tp.display_name, tp.quantity, tp.show_slug
  from public.ticket_posts tp
 where tp.price_type <> 'free'
 order by tp.created_at desc;
