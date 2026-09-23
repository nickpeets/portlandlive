-- Stories, part 2 (Sep 23 2026): the stories bucket also takes audio (MP3 /
-- M4A) up to 25 MB. Run once in the Supabase SQL Editor; re-running is safe.
-- Depends on schema-stories.sql. Upload rights are unchanged: writers only.
update storage.buckets
   set file_size_limit = 26214400,
       allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp', 'audio/mpeg', 'audio/mp4', 'audio/x-m4a']
 where id = 'stories';

select id, file_size_limit, allowed_mime_types from storage.buckets where id = 'stories';
