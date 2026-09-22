-- Run inside SQLcl after adb-connect ADMIN (or the workspace schema).
set serveroutput on
select user as connected_schema from dual;
select version_no as apex_version from apex_release;
declare
  version_text varchar2(100);
  major_version number;
  minor_version number;
begin
  select version_no into version_text from apex_release;
  major_version := to_number(regexp_substr(version_text, '[0-9]+', 1, 1));
  minor_version := to_number(regexp_substr(version_text, '[0-9]+', 1, 2));
  if major_version < 26 or (major_version = 26 and minor_version < 1) then
    raise_application_error(-20001, 'APEX 26.1+ is required. Check the ADB APEX upgrade schedule.');
  end if;
  dbms_output.put_line('APEXlang version prerequisite: OK');
end;
/
