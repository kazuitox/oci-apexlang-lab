-- This stage connects as APEXLAB with the shared password, not ADMIN.
declare
  v_count number;
begin
  if user <> 'APEXLAB' then
    raise_application_error(-20047, 'Unexpected connected schema');
  end if;
  select count(*) into v_count from user_sys_privs where privilege = 'CREATE SESSION';
  if v_count = 0 then
    raise_application_error(-20048, 'CREATE SESSION direct grant is missing');
  end if;
  select count(*) into v_count from session_roles where role = 'DWROLE';
  if v_count = 0 then
    raise_application_error(-20049, 'DWROLE is not enabled');
  end if;
  select count(*) into v_count from user_ts_quotas where tablespace_name = 'DATA' and max_bytes = -1;
  if v_count = 0 then
    raise_application_error(-20050, 'DATA unlimited quota is missing');
  end if;
  select count(*) into v_count from apex_workspaces where workspace = 'APEXLAB';
  if v_count <> 1 then
    raise_application_error(-20051, 'Workspace is not visible to APEXLAB');
  end if;
end;
/
