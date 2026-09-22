# OCI上のAPEXlangアプリ開発

## 最初に守る作業方針

日本語で回答する。ユーザーの要件からAPEXlangのソースを生成・編集・検証する。
作業の起点はVM上の `/home/opc/projects/apex-study`。アプリはその配下に置く。
**基本の順序は、RMデプロイ（AnsibleでAPEX初期設定・接続確認まで実行）→ Codex認証 → アプリ作成。**
ユーザーが現在の環境で初回準備を完了したと報告している場合、同じ準備を聞き直したり再実施させたりしない。
Codex自身によるひな形生成・構文検証は `sql -L /nolog` で行える。保存済みSQLcl接続やCodexが扱うDBパスワードはこの工程では不要。
アプリ生成物がない場合もCodex自身が生成する。ひな形を作るためだけにユーザーへ手動DB接続を要求しない。
ソース生成・検証と、ADBへのインポート・ブラウザでの動作確認は別工程として扱う。

## 配備時の初期設定と確認

1. Resource Managerでデプロイする。既定の `initialize_apex = true` では、AnsibleがDBユーザー・Workspace・APEX画面用ユーザーをすべて `APEXLAB` で作成する。
2. CREATE SESSION・DWROLE・DATA quota unlimitedを設定し、APEX 26.1以上、APEXLABでのDB接続、Workspaceの関連付け、APEXアカウントのパスワードを検証する。
3. 検証結果は `/var/lib/apexlang/apex-ready.json`。`adb_ocid` と `adb_name` が `/etc/apexlang/config.json` と一致し、`database_login_verified` / `apex_account_password_verified` がtrueなら、その時刻に初期設定確認済み。WebでWorkspaceを作成させたり、同じ権限を再付与させたりしない。
4. `/home/opc/projects/apex-study` で `codex` を起動してアプリを作成する。

**初期パスワードは、DB ADMIN・DB APEXLAB・APEX画面用APEXLABですべて同じ。RMで指定したADB ADMINパスワードを使う。** 実値は初期化完了・失敗時にVMから削除する。通常の設定・AGENTS.md・プロンプト・ログには含めない。SQLclの保存接続は作成しない。手動接続するときは `adb-connect APEXLAB` のプロンプトでユーザーが入力する。

Workspace名・解析スキーマ名・APEX画面用ユーザー名は `APEXLAB` と確定している。これらの名前をユーザーへ質問しない。名前だけを根拠に、接続や初期設定まで完了したと判断しない。

`initialize_apex = false`、確認ファイルがない、またはADBが一致しない場合は、自動準備が確認できていないと報告する。ソース作成・構文検証は進められる。手動初期化が必要な場合はREADMEの手順を使い、可否確認だけでDBを変更しない。

再Applyは作成済みユーザーとWorkspaceを再利用する。既存パスワード・Workspace関連付けが異なる場合に削除・上書き・リセットはしない。READYは最後の検証記録であり、現在のブラウザログイン・アプリ動作の検証を意味しない。

## 設定値と実環境の状態を区別する

| 項目 | このプロジェクトの扱い |
| --- | --- |
| 解析スキーマ名 | `APEXLAB`。初回準備で作成・権限付与する対象。名前は聞き直さず、準備の完了は現在の環境の報告・実行結果で判断する |
| Workspace名 | `APEXLAB`。Ansibleの自動初期化で作成・検証。名前の質問は不要 |
| アプリalias | ユーザーの指定を使う。指定がなければ機能に合う未使用のaliasを選ぶ |
| 既存アプリ | 作業ディレクトリの実ファイルで判断する。`testapp` 等が存在するとは仮定しない |
| SQLcl保存接続 | 配備では作成しない。ソース生成・接続不要の検証には不要 |
| DB接続とAPEXバージョン確認 | 現在の接続先での実行結果がある場合だけ確認済みとする |

過去の別ADB・別VMでの接続成功やアプリ生成を、現在の環境の完了状態として扱わない。
ADBのOCID・DB名は `/etc/apexlang/config.json` で確認し、過去ログのDB名を接続先へ流用しない。
Terraform/Ansibleは既定でAPEXLABのDBユーザー・Workspace・APEXユーザーまで作成する。アプリとSQLcl保存接続は作成しない。初期設定の実行結果は現在のADBと確認ファイルの照合で判断する。
`APEXLAB` という設定名を知っていることと、現在のADBにそのユーザーが作成済みであることを混同しない。

Workspace名を `なし`、`none` 等で埋めない。既定は実際に作成する `APEXLAB`。既存アプリの有効な設定は保持する。

## 環境とツール

| 項目 | 設定・確認先 |
| --- | --- |
| 実行ユーザー | `opc`。SQLclとCodexはsudoで起動しない |
| VM | Oracle Linux 8 / Arm64、2 OCPU / 12 GB |
| DB | OCI Autonomous Database。APEXとORDSはADB側のマネージドサービス |
| DB構成 | `/etc/apexlang/config.json` の `adb_ocid`、`adb_name`、`region`、`auto_wallet` |
| SQL接続サービス | 設定ファイルの `adb_name` に `_low` を付ける |
| Wallet | `/home/opc/.adb/wallet.zip`。opc所有、0600。DBユーザーの作成やパスワード認証を代替しない |
| 対話DB接続ヘルパー | `adb-connect <Database User>`。初回接続確認・DB反映時に使う。SQLclの保存接続名ではない |
| SQLcl | `/usr/local/bin/sql` → `/opt/apexlang/sqlcl`。構築時の指定は26.2.2.233.1901 |
| Java | `/opt/apexlang/jdk`、JDK 21 |
| Codex | `/home/opc/.local/bin/codex` |
| Oracle APEXlangスキル | `/home/opc/.agents/skills/apexlang/SKILL.md` |
| シェル設定 | `/etc/profile.d/apexlang.sh`。LANG / LC_ALLは `en_US.UTF-8` |
| 構築状況 | `apexlang-status`、`/var/lib/apexlang/tool-versions.txt`、`/var/lib/apexlang/apex-ready.json` |
| APEXの入口 | Resource Managerの出力 `apex_url`、またはOCIコンソールのADB → APEX |

Walletは通常AnsibleがInstance Principalで取得する。`auto_wallet=false` なら手動配置が必要だが、DB未接続のソース生成・検証は進められる。
`apexlang-status` のtools/wallet READYだけをDB認証・Workspace確認済みと解釈しない。apex READYは最後のDB/API検証記録で、アプリやブラウザの確認ではない。
VMへORDSを追加インストールする必要はない。

## ソース作成の開始手順

1. このファイル、対象アプリの既存の指示・README・要件を読む。
2. インストール済みのOracle APEXlangスキルを読み、構文資料・補助ツールを利用する。
3. 作業ディレクトリ内で `application.apx`、`pages/`、`deployments/default.json` の実在を確認する。既存アプリがあればユーザーの指定に従って使い、再生成しない。
4. 新規ならユーザーの要件からaliasと出力先を決め、同名のディレクトリやファイルがないことを確認して、下記のDB未接続の手順で生成する。
5. `.apx` を編集して接続不要の検証を実行する。保存接続がないことやプロンプトでWorkspace名が未指定であることを理由に、この工程を止めない。

VMのBashで実行する例（`studyapp` は選んだaliasへ置換する）：

```bash
source /etc/profile.d/apexlang.sh
cd /home/opc/projects/apex-study
if [ -e ./studyapp ] || [ -L ./studyapp ]; then
  echo 'studyapp already exists; inspect and edit it instead of generating over it.'
else
  sql -s -L /nolog <<'SQL'
apex generate -alias studyapp
apex validate -input ./studyapp
exit
SQL
fi
```

`apex` はSQLcl内のコマンドであり、Bashで `apex` だけを実行しない。
`apex generate` は既存ファイルを上書きし得るため、生成先の事前確認を必須とし、`-force` を使わない。
パスに空白や特殊文字を含めず、ユーザーの文章をそのままSQLclコマンドへ埋め込まない。
SQLclの終了コードだけで成功と判断せず、生成ファイルの実在と検証出力の `Validation successful`、エラー・警告を確認する。

SQLcl 26.2.2でDB未接続の生成・検証を確認済み。接続がない旨と使用するAPEXlangバージョンの表示は、生成失敗を意味しない。
この場合、SQLclが対応するAPEXlangバージョンを使うため、ADB側APEXとの整合はインポート段階で別途確認する。
生成された `deployments/default.json` が空のJSONオブジェクトでも、構文検証を進められる。Workspaceを埋めるためだけにユーザーへ質問しない。
`.apex/apexlang.json` の `mmdVersion` を、検証エラーを回避する目的で変更しない。

スキルの既定手順がWorkspace名・保存接続・Live DB検証を要求しても、ソース作成と接続不要の検証では本プロジェクトの手順を優先する。
必須入力がないスキルの生成・Live DB用ツールを仮値で呼ばず、SQLclの `generate` / `validate` とスキルの構文資料を使う。
接続不要の検証成功をLive DB検証成功とは報告しない。

## 編集と検証

- 機能要件から画面・操作・ナビゲーションとデータモデルを整理して実装する。
- 既存テーブル・列・キーは提供DDLやメタデータで確認する。DBへ接続できなければ既存構造を推測しない。新規アプリ用のテーブルはDDLとして設計し、未適用であることを明示する。
- 生成物・インストール済みスキル・SQLclヘルプで構文と属性を確認し、存在しないキーやAPEXlang構文を作らない。
- 既存の認証・認可設定やアプリを保持し、編集後に再検証する。
- パスワード、Walletの内容、秘密鍵、`~/.codex/auth.json` の内容を読み出してチャット・ソース・ログへ載せない。

編集後の検証はVMのBashからCodex自身が実行する：

```bash
sql -s -L /nolog <<'SQL'
apex validate -input /home/opc/projects/apex-study/studyapp
exit
SQL
```

対象パスを実際のアプリへ置換する。失敗したら原因を調べて修正し、再検証する。
DBオブジェクトの存在・権限・実際のAPEXバージョンとの整合・ブラウザ動作は、この検証だけでは確認できない。
ソース作成後の報告には、変更ファイル・実装機能・実際の検証結果・未適用のDDL・DBインポートの実行状況を記載し、未実行なら手動インポートの手順を提示して作業者に実行を促す。

## アプリ作成後について

アプリが作成できたらインポートまで進める。インポートは手動で必要なので、Codexは対象アプリに合わせた手順を提示し、作業者に実行を促す。追加のインポート依頼を待たず、ソース作成・構文検証だけで作業完了としない。

## DBへの反映手順（作業者が手動で実行）

初回準備で確認した、現在のADBの開発用ユーザー・認証・Workspace・APEXバージョンを使う。準備済みという現在の環境の報告があれば、再作成・再付与を要求しない。
解析スキーマは `APEXLAB`。名前を質問し直さず、現在のADBの設定と整合することを確認する。
有効な保存接続がある場合はそれを利用できるが、この構築では保存接続を用意しない。
`adb-connect` は対話接続用であり、保存接続の代わりにはならない。共通パスワードは初期化時のみ渡し、完了後はVMに保存していない。
認証が未準備ならDB反映だけを未実行として報告する。ソース生成・編集・接続不要の検証を巻き戻したり、手動接続待ちにしたりしない。

DBユーザーを確認する必要がある場合、ユーザーがVMのBashで `adb-connect ADMIN` を実行し、現在のADBのADMINパスワードを対話入力する。SQLcl内の読み取り専用SQL：

```sql
select username, account_status
from dba_users
where username = 'APEXLAB';
```

0行なら現在のADBにAPEXLABは存在しない。行があってもパスワードの正しさやログイン成功までは証明しない。
`ORA-01017` はユーザー名・パスワード・接続先・認証条件を確認するエラー。ログだけで「パスワード入力ミス」や「ユーザー不在」と断定しない。
`ORA-01045` はCREATE SESSION権限不足。01017と混同しない。
既存ユーザーを削除・再作成したり、パスワードを勝手に変更したりしない。必要な初回設定はDB反映の範囲で扱う。

開発用ユーザーで接続できたら `@/opt/apexlang/verify-apex.sql` でAPEX 26.1以上を確認する。
Workspace名は質問せず、既存設定・接続先から反映先を解決する。解決できなければインポートは実行せず理由を報告する。
Workspace名をユーザーに入力させないことと、APEXアプリの実行先Workspaceそのものが不要であることを混同しない。

対象が解決できたら、作業者に次の手順を提示して実行を促す。対象パスは実際のアプリへ置換する。

まずVMのBashで接続し、パスワードは作業者が対話入力する：

```bash
adb-connect APEXLAB
```

続いて、解析スキーマで接続したSQLcl内で作業者が実行する：

```sql
apex validate -input /home/opc/projects/apex-study/studyapp
apex import -input /home/opc/projects/apex-study/studyapp
```

検証成功後にインポートする。既存アプリの置換、DDL、データ削除は承認済みの対象と範囲を守る。
インポート成功とブラウザ動作確認を区別し、未実行の工程を完了扱いにしない。

## アプリ用デモアカウントのパスワード管理

ユーザーがVM内テキストファイルでの保管を明示的に希望した場合に限り、アプリ用デモアカウントのランダムパスワードを次の方針で扱う。

- 保存先はGit管理外の `/home/opc/.apexlang-secrets/` 配下とする。
- ディレクトリは `0700`、パスワードファイルは `opc` 所有・`0600` とする。
- ランダム値は十分な長さで生成し、コマンド出力・Codexのチャット・ソース・README・AGENTS.md・ログへ値そのものを出さない。
- Codexはパスワードファイルの内容を読み出したり表示したりしない。値の確認はユーザーがVMの対話端末で行う。
- ファイルにはパスワードだけを保存し、ファイル名から対象アプリ・ユーザーを識別できるようにする。例: `/home/opc/.apexlang-secrets/todoapp-demo-password.txt`
- 既存のAPEXユーザーに対して `APEX_UTIL.CREATE_USER` を再実行してパスワード更新を試みない。重複時はWorkspace管理画面で対象ユーザーのパスワードを再設定・ロック解除する。
- パスワードの削除・ローテーションは、ユーザーから明示的な依頼があった場合にだけ行う。

## APEX URLとアプリURL

- APEXの正しい入口URLは、ADB名から組み立てない。Resource Manager出力 `apex_url` を正とする。
- ADBの公開APEX URLには `oraclecloudapps.com` を含む場合がある。
- アプリのフレンドリーURLは次の形式：
  `https://<apex-host>/ords/r/<workspace-lowercase>/<app-alias-lowercase>/<page-alias-lowercase>`
- APEX Builder／Workspace管理は `apex_url`（例: `/ords/apex`）から開く。アプリ実行URLのログイン画面にはユーザー管理メニューはない。

## Codexの起動位置

この `AGENTS.md` がある `/home/opc/projects/apex-study` で `codex` を起動し、対象アプリの子ディレクトリを指定する。
Gitのプロジェクトルートがない場合、子ディレクトリで起動しても親の `AGENTS.md` が自動で読まれるとは限らない。
子ディレクトリで起動する場合は指示の読み込みを確認し、既存の指示ファイルを上書きしない。

## 参考

- [Oracle SQLclのAPEXlangコマンド](https://docs.oracle.com/en/database/oracle/sql-developer-command-line/26.1/sqcug/apexlang.html)
- [Oracle SQLclのAPEXlangワークフロー](https://docs.oracle.com/en/database/oracle/sql-developer-command-line/26.1/sqcug/common-workflows.html)
- [Oracle APEXlangスキル](https://github.com/oracle/skills/tree/main/apex/apexlang)
- [ORA-01017](https://docs.oracle.com/en/error-help/db/ora-01017/)
- [ADBでのWorkspace作成](https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/apex-create-workspace.html)
- [ADBのロール・権限](https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/manage-users-privileges.html)
- [ADBで利用可能なAPEX管理API](https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/apex-notes-autonomous.html)
- [CodexのAGENTS.md読み込み規則](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
