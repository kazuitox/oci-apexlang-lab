-- The helper substitutes a SQL-escaped literal in memory. Never save rendered SQL.
declare
  v_count number;
  v_status varchar2(100);
  v_password varchar2(128) := @@PASSWORD_LITERAL@@;
begin
  select count(*) into v_count from dba_users where username = 'APEXLAB';
  if v_count = 0 then
    execute immediate 'create user APEXLAB identified by "' || v_password || '" default tablespace DATA';
    dbms_output.put_line('APEXLANG_CHANGED');
  end if;
  select account_status into v_status from dba_users where username = 'APEXLAB';
  if v_status <> 'OPEN' then
    raise_application_error(-20042, 'Existing APEXLAB is locked or expired; no password reset was performed');
  end if;
  select count(*) into v_count from dba_sys_privs
    where grantee = 'APEXLAB' and privilege = 'CREATE SESSION';
  if v_count = 0 then
    execute immediate 'grant create session to APEXLAB';
    dbms_output.put_line('APEXLANG_CHANGED');
  end if;
  select count(*) into v_count from dba_role_privs
    where grantee = 'APEXLAB' and granted_role = 'DWROLE';
  if v_count = 0 then
    execute immediate 'grant dwrole to APEXLAB';
    dbms_output.put_line('APEXLANG_CHANGED');
  end if;
  select count(*) into v_count from dba_ts_quotas
    where username = 'APEXLAB' and tablespace_name = 'DATA' and max_bytes = -1;
  if v_count = 0 then
    execute immediate 'alter user APEXLAB quota unlimited on DATA';
    dbms_output.put_line('APEXLANG_CHANGED');
  end if;
end;
/
