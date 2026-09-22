declare
  v_password varchar2(128) := @@PASSWORD_LITERAL@@;
  v_valid boolean;
  v_roles varchar2(4000);
begin
  apex_util.set_workspace(p_workspace => 'APEXLAB');
  if apex_util.get_user_id(p_username => 'APEXLAB') is null then
    apex_util.create_user(
      p_user_name => 'APEXLAB',
      p_web_password => v_password,
      p_developer_privs => 'ADMIN:CREATE:DATA_LOADER:EDIT:HELP:MONITOR:SQL',
      p_default_schema => 'APEXLAB',
      p_allow_access_to_schemas => 'APEXLAB',
      p_account_locked => 'N',
      p_change_password_on_first_use => 'N');
    -- Authentication may use a separate transaction; make the new account visible first.
    commit;
    dbms_output.put_line('APEXLANG_CHANGED');
  end if;
  v_roles := apex_util.get_user_roles(p_username => 'APEXLAB');
  if v_roles is null or instr(':' || v_roles || ':', ':ADMIN:') = 0 then
    raise_application_error(-20045, 'Existing APEX user does not have workspace administrator privileges');
  end if;
  v_valid := apex_util.is_login_password_valid(p_username => 'APEXLAB', p_password => v_password);
  if v_valid is null or not v_valid then
    raise_application_error(-20046, 'APEX account password differs; no password reset was performed');
  end if;
end;
/
