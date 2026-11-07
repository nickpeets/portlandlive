-- Google / Apple sign-in (Nov 6 2026): name new accounts from what the
-- provider sends. Email sign-up still sends display_name and wins; Google
-- sends full_name / name; Apple's web sign-in usually sends no name, so the
-- email's first half is used unless it's an Apple private-relay address.
-- Handle logic is unchanged from schema-handles.sql: no handle sent ->
-- one is made from the name and the one-time rename stays available.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_display_name text;
  v_handle text;
  v_backfilled boolean := false;
  v_constraint text;
  v_email_name text;
begin
  v_email_name := case
    when new.email is null or new.email ilike '%@privaterelay.appleid.com' then null
    else nullif(trim(split_part(new.email, '@', 1)), '')
  end;
  v_display_name := left(coalesce(
    nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''),
    nullif(trim(new.raw_user_meta_data ->> 'full_name'), ''),
    nullif(trim(new.raw_user_meta_data ->> 'name'), ''),
    v_email_name,
    'New user'
  ), 60);
  v_handle := nullif(trim(new.raw_user_meta_data ->> 'handle'), '');

  if v_handle is null then
    v_handle := public.generate_handle(v_display_name, new.id);
    v_backfilled := true;
  elsif v_handle !~ '^[a-zA-Z0-9_]{3,20}$' then
    raise exception 'handle_invalid' using errcode = 'check_violation';
  elsif lower(v_handle) = any (public.handle_reserved_words()) then
    raise exception 'handle_reserved' using errcode = 'check_violation';
  end if;

  insert into public.profiles (id, display_name, handle, handle_rename_available)
  values (new.id, v_display_name, v_handle, v_backfilled);
  return new;
exception
  when unique_violation then
    get stacked diagnostics v_constraint = constraint_name;
    if v_constraint = 'profiles_handle_lower_idx' then
      raise exception 'handle_taken' using errcode = 'unique_violation';
    end if;
    raise;
end;
$$;

select 'OAUTH NAMES OK' as result;
