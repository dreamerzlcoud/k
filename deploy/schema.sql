-- Run once in the dedicated InkLab Supabase project.
create table if not exists public.inklab_workspaces (
  user_id uuid primary key references auth.users(id) on delete cascade,
  version bigint not null default 1 check(version > 0),
  archive_path text not null,
  size_bytes bigint not null check(size_bytes between 0 and 50000000),
  updated_at timestamptz not null default now()
);
alter table public.inklab_workspaces enable row level security;
create policy "owner reads workspace" on public.inklab_workspaces for select to authenticated using (user_id=(select auth.uid()));
-- Changes only through the CAS function; direct user writes are not granted.
grant select on public.inklab_workspaces to authenticated;
revoke insert,update,delete on public.inklab_workspaces from anon,authenticated;

create schema if not exists inklab_private;
revoke all on schema inklab_private from public;
grant usage on schema inklab_private to authenticated;
create or replace function inklab_private.commit_workspace(expected_version bigint,new_archive_path text,new_size bigint)
returns bigint language plpgsql security definer set search_path='' as $$
declare uid uuid := auth.uid(); next_version bigint;
begin
  if uid is null or new_size not between 0 and 50000000 or
     new_archive_path !~ ('^'||uid::text||'/[a-f0-9]{32}\.zip$') then
    raise exception 'invalid workspace';
  end if;
  if expected_version=0 then
    insert into public.inklab_workspaces(user_id,archive_path,size_bytes)
    values(uid,new_archive_path,new_size) on conflict do nothing returning version into next_version;
  else
    update public.inklab_workspaces set version=version+1,archive_path=new_archive_path,size_bytes=new_size,updated_at=now()
    where user_id=uid and version=expected_version returning version into next_version;
  end if;
  if next_version is null then raise exception 'workspace version conflict'; end if;
  return next_version;
end $$;
revoke all on function inklab_private.commit_workspace(bigint,text,bigint) from public;
grant execute on function inklab_private.commit_workspace(bigint,text,bigint) to authenticated;
create or replace function public.inklab_commit_workspace(expected_version bigint,new_archive_path text,new_size bigint)
returns bigint language sql security invoker set search_path='' as $$
  select inklab_private.commit_workspace(expected_version,new_archive_path,new_size);
$$;
revoke all on function public.inklab_commit_workspace(bigint,text,bigint) from public;
grant execute on function public.inklab_commit_workspace(bigint,text,bigint) to authenticated;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('inklab-private','inklab-private',false,50000000,array['application/zip']) on conflict(id) do nothing;
create policy "owner reads snapshots" on storage.objects for select to authenticated
using(bucket_id='inklab-private' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy "owner creates snapshots" on storage.objects for insert to authenticated
with check(bucket_id='inklab-private' and (storage.foldername(name))[1]=(select auth.uid())::text);
create policy "owner deletes snapshots" on storage.objects for delete to authenticated
using(bucket_id='inklab-private' and (storage.foldername(name))[1]=(select auth.uid())::text);
