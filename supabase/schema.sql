-- PortlandLive — Fork Stage 1: accounts + display names
--
-- Run this once, in full, in the Supabase SQL Editor for the project
-- (Dashboard -> SQL Editor -> New query -> paste -> Run) BEFORE the app's
-- sign-up flow is used. It needs elevated privileges (creating a trigger on
-- auth.users) that the anon/public API key cannot do, which is why this
-- can't be applied from client-side code.
--
-- Scope, intentionally minimal for Stage 1:
--   - auth.users (Supabase-managed) is the identity source of truth.
--   - public.profiles holds exactly one extra field: display_name.
--   - display_name is NOT unique, NOT a handle, NOT searchable/browsable.
--     It exists only so a user can be shown a human-readable name for
--     themselves right now. Thread-visibility (someone else's display_name,
--     scoped to a shared trade thread) is explicitly OUT of scope here and
--     will need its own SELECT policy added in the messaging stage.

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text not null,
  created_at timestamptz not null default now(),
  constraint display_name_length check (
    char_length(trim(display_name)) between 1 and 60
  )
);

alter table public.profiles enable row level security;

-- Drop-and-recreate so this script is safe to re-run if a policy needs tweaking.
drop policy if exists profiles_select_own on public.profiles;
drop policy if exists profiles_insert_own on public.profiles;
drop policy if exists profiles_update_own on public.profiles;

-- Stage 1: a user may read ONLY their own profile row. There is no policy
-- allowing anyone to read another user's display_name yet -- that is
-- deliberate. When the messaging stage lands, add a SELECT policy scoped to
-- "the other participant in a thread I'm also in" (e.g. via an EXISTS
-- subquery against the thread-participants table), never a blanket
-- "authenticated users can read all profiles" policy.
create policy profiles_select_own
  on public.profiles
  for select
  using (auth.uid() = id);

create policy profiles_insert_own
  on public.profiles
  for insert
  with check (auth.uid() = id);

create policy profiles_update_own
  on public.profiles
  for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- No delete policy: a profile row is removed only via the auth.users
-- cascade (i.e. full account deletion), never a standalone row delete.

-- Auto-create the profile row the moment an auth.users row is created, so
-- signup works correctly even when email confirmation is enabled (the
-- client has no session -- and thus no auth.uid() -- until the user
-- confirms/logs in, so a client-side insert immediately after signUp()
-- would be rejected by RLS). display_name is read from the signUp() call's
-- options.data.display_name, which Supabase stores on
-- auth.users.raw_user_meta_data.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    coalesce(nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''), 'New user')
  );
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
