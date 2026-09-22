# ローカル検証

OCIの認証情報を使用せずに実行します。2026-09-20にmacOS Arm64上で検証しました。
1.4.7の作業ディレクトリ・AGENTS.md配置を追加後、2026-09-21に同じ48テストとTerraform/RMスキーマ検証を再実行しました。

## 実行方法

Terraform 1.5.7とPython 3.11以降を準備してください。

```bash
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
python3 -m venv .venv
.venv/bin/pip install -r tests/requirements.txt
TERRAFORM=terraform .venv/bin/python -m unittest discover -s tests -v
.venv/bin/ansible-playbook -i localhost, -c local --syntax-check playbooks/site.yml
.venv/bin/python tests/validate_rm_schema.py
python3 scripts/build_zip.py
```

`terraform init` はOCI・Random・TLS Providerを取得します。乱数テストはローカルの `.terraform/providers` を使用します。スキーマ検証はOracle公式HTMLを取得し、掲載メタスキーマへ照合します。保存済みHTMLを引数に指定することもできます。

## 実施結果

| 検証 | 結果 |
| --- | --- |
| Terraform 1.5.7 / OCI 9.2.0 / Random 3.7.2 / TLS 4.1.0 init | 成功 |
| Terraform validate / fmt | 成功 |
| Provider lock | linux_amd64 / darwin_arm64の公式署名付き配布のチェックサムを収録 |
| Resource Manager schema | Oracle公開メタスキーマへの適合を確認 |
| Ansible Core 2.19.8 syntax-check | 成功 |
| unittest | **48テスト成功** |
| 1.4.6 シェルの既定ロケール | Ansibleで既存の.bashrcを保持して設定し、再実行で変更なし。profile読込と対話BashでLANG・LC_ALL・UTF-8を確認 |
| 1.4.7 アプリ作業ディレクトリ | 実際のAnsibleタスクを一時ディレクトリで実行し、AGENTS.mdの配置・0644/0755・再実行で変更なし・利用者の編集と既存アプリの保持を確認 |
| 1.4.8 DB未接続のアプリ生成・検証 | SQLcl 26.2.2 / JDK 21で実行し、ひな形生成、空のdeployment設定、Validation successfulを確認。DB接続や保存接続は不使用 |

1.4.9では、初回準備をRMデプロイ → Workspace/スキーマ作成 → ADMINで権限付与・APEXLAB接続確認 → Codexの順に整理しました。CREATE SESSION・DWROLE・DATA quotaと確認SQL、VMのSQLclからのADD_WORKSPACE API例を公式仕様に照合しています。これは手順・出力案内の変更で、SQLの実DB実行やResource Manager Applyは行っていません。

## 1.5.1のOracleスキル取得・復旧

2026-09-22、Ansible Core 2.19.8とmacOS上の一時ディレクトリを使用して確認しました。追加した `test_oracle_skills.py` は外部通信をせず、実際のGitと本番と同じAnsibleタスクをローカルリポジトリへ実行します。実行ユーザー・所有者だけをテスト用に置き換えています。

既存分を含む **60テストが成功**しました。Terraform 1.5.7の `validate` / `fmt -check`、Ansible構文検証、保存済みOracle公開RMメタスキーマとの照合も成功しています。

- APEXlangのない既定ブランチを用意し、旧設定で `Require the APEXlang skill` の失敗を再現。取得済みの浅いcloneを修正版で固定コミットへ復旧。
- 新規取得でも既定ブランチに依存せず固定コミットを選択。`main` が固定コミットより先へ進んでいても、その固定コミットを取得。
- `SKILL.md`、補助ファイル、登録先リンク、コミット記録、ログのSHAを確認。再実行は `changed=0`。
- 利用者による追跡対象ファイルの編集がある場合、checkoutを失敗させて編集内容と元のコミットを保持。
- 指定コミットにスキルがない場合、SHAと期待パスを表示して失敗し、登録・コミット記録へ進まない。

さらに実際の `https://github.com/oracle/skills.git` を浅くcloneし、既定ブランチ `add-mle-javascript-skill-to-index` / `4e91e91590124502af8255d05594319445e9f39a` に対象ファイルがないことと、旧タスクの終了コード2を確認しました。同じcloneへ修正版を実行すると `b94ccf4dec34b27859c2378fa71ba2bad884f2fe` へ移り、スキルと `tools/apexctl.mjs`、リンク、コミット記録を確認して終了コード0、2回目は `changed=0` でした。この公開リポジトリの確認は通常のオフラインテストとは別に行っています。

**OCIのPlan/Apply、OL8上のopcユーザーによる実行、スキルを用いたアプリ生成、Wallet取得、APEX初期化はこのテストでは実行していません。**

## 1.5.0のAPEX自動初期化

2026-09-21、macOS Arm64上で **56テスト成功**、Terraform validate/fmt、Ansible Core 2.19.8 syntax-check、Oracle公開RMメタスキーマへの適合を確認しました。

- 実際のAnsibleで5工程を模擬実行し、工程名の表示と秘密入力の秘匿を確認。途中のSQLエラー番号だけを表示し、後続工程・READY記録へ進まないことを確認。
- SQLclプロセスの引数・環境変数にパスワードを入れず、標準入力で渡す。引用符・アンパサンド・ドル・バッククォート等を含むダミーパスワードのSQL文字列化を確認。
- 終了コード0でも成功マーカーがない場合、SQLエラーがある場合は失敗。失敗・タイムアウト時のSQLcl一時ホーム削除を確認。
- OS初期化で失敗したケースをシェル関数で模擬し、アップロード元と実行用パスワード一時ファイルが削除され、失敗コードが維持されることを確認。
- 共通パスワードにAPEXLAB・制御文字を含む場合をTerraformが拒否し、APEX自動初期化とWallet手動配置の矛盾をPlan時に拒否することを確認。
- 実際のSQLcl 26.2.2 / JDK 21で、バッチ実行に使うSET・WHENEVER・EXITの設定をDB未接続で受理することを確認。

**PL/SQLの実DB実行、ADB上のユーザー・Workspace作成、パスワード認証、再実行時のDB状態保持、OL8上の一連の処理、RM Apply、APEXのブラウザログインは未検証です。** SQL/APIはOracle公式仕様と照合しました。ローカルの模擬成功を実ADBでの成功として扱いません。

主な検証範囲：

- ハイフン付き表示名と英数字のみのDB内部名を生成する。
- 自動命名・固定名、Prefixの文字種と長さ、乱数のstate保持、独立したstateの名前の分離。
- 有料の非ホームリージョン配置とAlways Freeのホームリージョン制限。
- ADB容量、接続元CIDR・ADMINパスワードの検証、VM公開IP /32を含むADB ACL。
- VMのcloud-initはOSアクセス設定だけを行い、ツール導入やWallet取得を起動しない。
- Ansibleの通常設定へ確定したADB OCID・DB名を渡し、ADMINパスワード・SSH秘密鍵を含めない。1.5.0のAPEX初期化用パスワードは別の一時ファイルで渡す。
- RMからの構成処理をVMと別のTerraformリソースに配置し、Private Endpoint経由で接続する。
- RM専用サブネットのTCP 22経路を許可し、Endpointの送信先をVMのプライベートIP /32へ限定する。
- Ansibleの構文と、Wallet取得の再試行条件・明示的無効時のスキップ条件。
- SQLcl配布物相当の `0640` のJARを実際のAnsibleタスクで `0644` にし、起動スクリプトは `0755`、対象外のWalletは `0600` を保つ。再実行は変更なし。
- SQLclの起動確認が失敗した場合、前回のtools.readyを削除してApply相当の処理を失敗させる。コマンドの終了コードが0でも成功マーカーがなければREADYにしない。
- 実際のAnsibleでWallet取得を2回失敗させてから成功させ、通常のログレベルでも各回の診断情報が出ることを確認する。例外本文のダミー機密情報は表示しない。
- OCI SDK 2.186.0が使用する実際のHTTPレスポンスで、非圧縮・gzip・deflateと取得済みの本文キャッシュを検証する。旧コードの `BadZipFile` をgzipレスポンスで再現し、修正後は元のZIPと一致する。
- HTTP圧縮の解除後のサイズ上限とレスポンスのclose、ZIP検証エラーの分類を確認する。実際のAnsibleで不正なWalletの終了コード2が再試行されず、Apply相当の処理が失敗することを確認する。
- 認証・Wallet生成API・ダウンロードの失敗段階を識別し、診断用callbackが `no_log` と対象タスクの制限を守る。
- `LC_ALL=C` で実際のAnsibleの起動失敗を再現し、起動スクリプトのUTF-8設定後はPlaybookが成功して日本語メッセージがログに残ることを確認する。PythonのUTF-8自動補正は無効にして検証する。
- 実際のAnsibleで意図的に失敗するPlaybookを実行し、TASK・PLAY RECAP・エラーがログへ出て終了コード2を返す。
- ログをteeへ渡しても成功0・失敗2/17・タイムアウト124を保持する。
- Wallet内から指定したlowサービスだけを選び、TCP 1522の接続先を抽出する。
- Wallet取得で指定されたADB OCIDを使用し、OCID未指定・空の場合はAPI呼び出し前に失敗する。
- WalletのZIP検証・権限・既存ファイル保護。
- 配布ZIPの許可リスト、ダミー秘密情報の除外、シェル構文、RMフォームの変数網羅。`apex-study` 配下のアプリや資格情報を追加しても、配布対象はAGENTS.mdだけになる。

Terraformの条件式はOCI応答をfixtureへ置き換えて評価します。Random Providerだけは一時ディレクトリで実際にApplyし、state保持を検証します。Ansibleのロケール・失敗伝播・リトライ診断テストはローカルのdebug/failタスクと一時フォルダの模擬コマンドだけを実行し、OS設定を変更しません。**上記ローカル検証は、OCIリソース本体のPlan/ApplyやOL8上の導入処理を実行した結果ではありません。**

### SQLcl公式配布物による追加検証

Oracle公式SQLcl `26.2.2.233.1901` ZIPのSHA1が公式掲載値 `a58830ea64d412ca7488a0bf014c8f01904b0414` と一致することを確認しました。ZIP内の `sqlcl/lib/dbtools-sqlcl.jar` は `0640` で、エラーに表示された `SqlCli.class` を含みます。JARを含む165ファイルが `0640`、起動スクリプトは `0755` です。

macOS Arm64とOracle JDK 21.0.12.1で、本体JARをテストユーザーが読めない権限にすると、ユーザー報告と同じ `ClassNotFoundException` と終了コード1が発生しました。検証用の一時フォルダに `chmod -R u=rwX,go=rX` を適用すると、`sql -s -L /nolog` が `prompt APEXLANG_SQLCL_READY` を実行して終了コード0を返し、バージョン表示も成功しました。JDKは公式SHA256と照合済みです。DB接続は行っていません。OL8のroot/opc間の所有権そのものを再現した試験ではありません。

## 1.4.8の案内に記載したDB未接続手順

2026-09-21、macOS Arm64の一時ディレクトリと新しいJavaユーザーホームを使い、Oracle SQLcl `26.2.2.233.1901` / JDK 21.0.12.1で以下を実行しました。SQLclは `-s -L /nolog` で起動し、接続資格情報を渡していません。

```sql
apex generate -alias offlinecheck
apex validate -input ./offlinecheck
exit
```

`application.apx` とページ等の生成、`deployments/default.json` が空のJSONオブジェクトであること、`mmdVersion=26.1.0+3102`、`Validation successful` と終了コード0を確認しました。SQLclはDB接続がないことと使用するスターターのバージョンを出力しますが、この表示は生成失敗ではありません。OL8 VM上での同手順や、ADB接続・インポートの検証結果ではありません。

## ユーザー提供ログで確認した範囲

2026-09-20 09:09〜09:14の修正前のApplyログでは、VM・ADB・Private Endpoint・Wallet用IAMの作成、RMからのSSH接続、OS初期化の完了、Python 3.11とAnsible Core 2.19.8の導入まで成功しています。その後、Ansible起動時のUTF-8ロケール検証で停止し、Playbookのタスクは始まっていません。

続く09:33〜10:07 UTCのApplyログでは、OL8 Arm64でのAnsible起動、JDK 21.0.12.1・SQLcl 26.2.2・Node.js 22.23.2・Codex CLI 0.155.1の導入とバージョン確認、APEXlangスキルの配置まで成功しています。Wallet取得は09:44:35から少なくとも10:07:39までリトライしていますが、添付ログには例外の種類やHTTPステータスがないため、原因は未確定です。

その後のユーザーによるWallet取得の手動実行では `BadZipFile, HTTP status=None` が確認されました。ローカルでHTTP圧縮を解除しない読み取りによる同じ例外を再現し、HTTP圧縮対応の修正後にユーザーからデプロイ成功の報告を受けています。実環境のレスポンスヘッダーや本文は取得していないため、実際のContent-Encodingは未確認です。

続くopcでの `adb-connect ADMIN` は `ClassNotFoundException` で失敗しました。ユーザー提供の `ls -l` 出力で本体JARがroot:root・0640であることを確認しました。その後、ユーザーは権限変更後のSQLcl起動・接続手順が成功したと報告しています。修正版Playbook全体の再Apply結果を確認したものではありません。

## 未検証の範囲

- 他のテナンシ・リージョンのIAM権限・Quota・A1容量、RM Private Endpointの作成とSSH接続
- 修正版のRM実画面でのフォーム表示・Plan・Apply・Destroy
- 1.4.6のSQLcl権限修正・opc起動確認・シェル既定ロケール設定を含むOL8 Arm64上のAnsible全タスク完走
- 1.4.7のAGENTS.md転送・opc所有での配置を含むResource Manager Applyと、VM上のCodexによる指示の読み込み
- デプロイ成功の報告と別に取得した、Instance PrincipalによるWallet取得やSecurity List・Internet Gateway・ADB ACLの実通信の詳細
- DB認証、APEXバージョン・Workspace作成、アプリ生成・検証・インポート

これらはデプロイ先のApplyログと、READMEの学習開始手順で確認します。
