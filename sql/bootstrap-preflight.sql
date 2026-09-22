-- ADMIN: fail before changing the database if APEXlang is unavailable.
declare
  v_version varchar2(100);
  v_major number;
  v_minor number;
  v_count number;
begin
  if user <> 'ADMIN' then
    raise_application_error(-20040, 'Bootstrap requires ADMIN');
  end if;
  select version_no into v_version from apex_release;
  select count(*) into v_count from session_roles where role = 'APEX_ADMINISTRATOR_ROLE';
  if v_count = 0 then
    raise_application_error(-20044, 'APEX_ADMINISTRATOR_ROLE is required');
  end if;
  v_major := to_number(regexp_substr(v_version, '[0-9]+', 1, 1));
  v_minor := to_number(regexp_substr(v_version, '[0-9]+', 1, 2));
  if v_major < 26 or (v_major = 26 and v_minor < 1) then
    raise_application_error(-20041, 'APEX 26.1 or later is required');
  end if;
end;
/
