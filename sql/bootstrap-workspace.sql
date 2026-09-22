declare
  v_count number;
  v_schemas varchar2(32767);
begin
  select count(*) into v_count from apex_workspaces where workspace = 'APEXLAB';
  if v_count = 0 then
    apex_instance_admin.add_workspace(
      p_workspace => 'APEXLAB', p_primary_schema => 'APEXLAB', p_additional_schemas => null);
    dbms_output.put_line('APEXLANG_CHANGED');
  end if;
  v_schemas := apex_instance_admin.get_schemas(p_workspace => 'APEXLAB');
  if v_schemas is null or instr(',' || replace(v_schemas, ' ', '') || ',', ',APEXLAB,') = 0 then
    raise_application_error(-20043, 'Workspace APEXLAB is not mapped to schema APEXLAB');
  end if;
end;
/
