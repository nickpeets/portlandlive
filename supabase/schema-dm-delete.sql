-- Delete your own direct message (Sep 17 2026).
--
-- Only the sender can delete, and only their own row; the other person's
-- messages are untouched. Deletion is permanent -- there is no "deleted
-- message" placeholder, the row is simply gone for both sides.
--
-- Run once, in full, in the Supabase SQL Editor.

create or replace function public.dm_delete(p_id bigint)
returns boolean language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  if auth.uid() is null then raise exception 'sign_in_required' using errcode = 'P0001'; end if;
  delete from public.dm_messages where id = p_id and sender_id = auth.uid();
  get diagnostics n = row_count;
  return n > 0;
end;
$$;
revoke all on function public.dm_delete(bigint) from public;
grant execute on function public.dm_delete(bigint) to authenticated;
