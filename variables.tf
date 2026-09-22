variable "tenancy_ocid" {
  type        = string
  description = "Resource Managerが設定するテナンシOCID。"
}

variable "compartment_ocid" {
  type        = string
  description = "ネットワーク、VM、ADBを作成する既存コンパートメント。"
}

variable "region" {
  type        = string
  description = "VM・ADB・ネットワークの配置リージョン。Always Free選択時のみホームリージョンが必要。"
}

variable "use_always_free" {
  type        = bool
  default     = false
  description = "trueはホームリージョンのAlways Free構成。false（既定）は有料ADB 2 ECPU / 20 GBで、ホームリージョン以外にも配置できます。有償テナンシかどうかからは自動判定しません。"
}

variable "availability_domain" {
  type        = string
  description = "A1 VMを配置する可用性ドメイン。"
}

variable "image_ocid" {
  type        = string
  description = "選択したリージョンのOracle Linux 8.10 aarch64プラットフォームイメージ。OCIDを固定して再Apply時の意図しないVM置換を防ぎます。"
  validation {
    condition     = can(regex("^ocid1\\.image\\.", var.image_ocid))
    error_message = "Oracle Linux 8.10 aarch64のイメージOCIDを指定してください。"
  }
}

variable "name_prefix" {
  type        = string
  default     = "apexlang"
  description = "リソース名の接頭辞。ADBの自動命名にも使用。IAM名はこの接頭辞を使用するため、複数スタックでは別の値を指定してください。作成後は変更せず維持します。"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,19}$", var.name_prefix))
    error_message = "先頭は小文字、3〜20文字の小文字・数字・ハイフンで指定してください。"
  }
}

variable "ssh_public_key" {
  type        = string
  description = "opcユーザーのSSH公開鍵。秘密鍵は入力しません。"
  validation {
    condition     = can(regex("^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+) [A-Za-z0-9+/=]+", trimspace(var.ssh_public_key)))
    error_message = "OpenSSH形式の公開鍵を指定してください。"
  }
}

variable "allowed_client_cidrs" {
  type        = string
  description = "VMのSSHとADBのSQL/APEXへの接続を許可するグローバルIPv4 CIDR。複数はカンマ区切り。0.0.0.0/0は禁止。"
  validation {
    condition = alltrue([
      for entry in split(",", var.allowed_client_cidrs) :
      can(cidrnetmask(trimspace(entry))) && try(tonumber(split("/", trimspace(entry))[1]) > 0, false)
    ])
    error_message = "有効なIPv4 CIDRをカンマ区切りで指定してください。例: 203.0.113.10/32。全公開の/0は使用できません。"
  }
}

variable "vcn_cidr" {
  type        = string
  default     = "10.60.0.0/16"
  description = "新規VCNのIPv4 /16。先頭の/24を公開サブネットに使用します。"
  validation {
    condition     = can(cidrnetmask(var.vcn_cidr)) && can(regex("/16$", var.vcn_cidr))
    error_message = "IPv4の/16 CIDRを指定してください。"
  }
}

variable "generate_adb_name" {
  type        = bool
  default     = true
  description = "ADB名をPrefixの英数字部分の先頭最大6文字＋8桁の乱数で生成。乱数はstateに保存し再Applyでも維持。固定名を使う場合はfalseにしてadb_nameへ未使用の名前を指定します。"
}

variable "adb_name" {
  type        = string
  default     = "APEXLANG"
  description = "自動命名が無効のときだけ使用する固定ADB名。同一テナンシ・リージョン内で一意。自動命名が有効なら、この値は使用しません。"
  validation {
    condition     = can(regex("^[A-Za-z][A-Za-z0-9]{0,13}$", var.adb_name))
    error_message = "ADB名は英字で始まる1〜14文字の英数字で指定してください。"
  }
}

variable "adb_version" {
  type        = string
  default     = "26ai"
  description = "対象リージョン・料金モードで提供されるDBバージョン。APEX自体は26.1以降が必要です。"
  validation {
    condition     = contains(["19c", "26ai"], var.adb_version)
    error_message = "19cまたは26aiを選択してください。"
  }
}

variable "adb_admin_password" {
  type        = string
  sensitive   = true
  description = "ADB ADMINと、初回作成するAPEXLABのDB/APEXアカウントで共用。初期化中のみVMへ渡します。Terraform stateには含まれます。"
  validation {
    condition = (
      length(var.adb_admin_password) >= 12 && length(var.adb_admin_password) <= 30 &&
      can(regex("[A-Z]", var.adb_admin_password)) && can(regex("[a-z]", var.adb_admin_password)) &&
      can(regex("[0-9]", var.adb_admin_password)) &&
      !can(regex("[\"\\r\\n]", var.adb_admin_password)) &&
      !strcontains(lower(var.adb_admin_password), "admin") &&
      !strcontains(lower(var.adb_admin_password), "apexlab") &&
      !can(regex("[[:cntrl:]]", var.adb_admin_password))
    )
    error_message = "12〜30文字、大文字・小文字・数字を各1文字以上含め、二重引用符・制御文字・admin・apexlabを含まないパスワードにしてください。"
  }
}

variable "initialize_apex" {
  type        = bool
  default     = true
  description = "AnsibleでAPEXLABのDBユーザー・Workspace・APEX画面用ユーザーを作成し、ADMINと同じ初期パスワードを設定。Wallet自動取得が必要です。"
}

variable "create_wallet_iam" {
  type        = bool
  default     = true
  description = "Wallet自動取得用Dynamic Group/Policyを作成。IAM作成権限がない場合はfalseにし、Walletを手動配置します。"
}

variable "codex_version" {
  type        = string
  default     = "latest"
  description = "Codex公式インストーラーのCODEX_RELEASE。latestまたは固定バージョン。"
  validation {
    condition     = var.codex_version == "latest" || can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.codex_version))
    error_message = "latestまたは0.123.0のようなバージョンを指定してください。"
  }
}

variable "provision_revision" {
  type        = string
  default     = "1"
  description = "同じ構成でAnsibleを再実行するときだけ値を変更。失敗後の再Applyでは自動再試行するため変更不要。"
  validation {
    condition     = can(regex("^[A-Za-z0-9._-]{1,32}$", var.provision_revision))
    error_message = "再実行番号は1〜32文字の英数字・ピリオド・ハイフン・アンダースコアで指定してください。"
  }
}
