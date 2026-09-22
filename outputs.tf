output "ssh_command" {
  description = "許可CIDRからSSH鍵で接続。必要に応じて-iを追加してください。"
  value       = "ssh opc@${oci_core_instance.dev.public_ip}"
}

output "vm_public_ip" {
  value = oci_core_instance.dev.public_ip
}

output "adb_ocid" {
  value = oci_database_autonomous_database.lab.id
}

output "apex_url" {
  value = oci_database_autonomous_database.lab.connection_urls[0].apex_url
}

output "database_actions_url" {
  value = oci_database_autonomous_database.lab.connection_urls[0].sql_dev_web_url
}

output "adb_low_service" {
  value = "${lower(local.effective_adb_name)}_low"
}

output "adb_database_name" {
  description = "実際に使用するADB名。自動命名時の乱数はstateに保存され、通常の再Applyでは変わりません。"
  value       = local.effective_adb_name
}

output "adb_display_name" {
  description = "OCIコンソール表示用のハイフン付き名称。SQL接続にはadb_database_nameを使用。"
  value       = local.adb_display_name
}

output "next_steps" {
  value      = var.initialize_apex ? "APEXLABのDBユーザー・Workspace・APEX画面用ユーザーを作成・検証済み。初期パスワードはRMに入力したADB ADMINと同じ。Codex初回認証後、/home/opc/projects/apex-studyでcodexを起動。" : "APEX自動初期化は無効。READMEの手動Workspace・スキーマ準備を実施してください。"
  depends_on = [terraform_data.configure]
}

output "apex_login" {
  description = "パスワードの実値は出力しません。ブラウザでのログイン試験は別途必要です。"
  value = var.initialize_apex ? {
    workspace        = "APEXLAB"
    username         = "APEXLAB"
    database_user    = "APEXLAB"
    initial_password = "RMで指定したADB ADMINパスワードと同じ"
  } : null
  depends_on = [terraform_data.configure]
}

output "codex_start_command" {
  description = "opcでVMにSSHログインし、初回認証後に実行。AGENTS.mdを置いたディレクトリで起動します。"
  value       = "cd /home/opc/projects/apex-study && codex"
  depends_on  = [terraform_data.configure]
}

output "wallet_iam_enabled" {
  value = var.create_wallet_iam
}

output "deployment_mode" {
  description = "選択した料金モード。VMとストレージの無料枠はテナンシ全体の使用量にも依存します。"
  value       = var.use_always_free ? "Always Free (home region only)" : "Paid ADB: 2 ECPU / 20 GB (LICENSE_INCLUDED)"
}

output "provisioning_status" {
  description = "Ansibleが完了した場合だけ成功状態を出力します。"
  value       = var.initialize_apex ? "Ansible completed: tools, wallet and APEXLAB ready; DB login and APEX account password verified" : (var.create_wallet_iam ? "Ansible completed: tools and wallet ready; APEX initialization disabled" : "Ansible completed: tools ready; manual wallet import required")
  depends_on  = [terraform_data.configure]
}
