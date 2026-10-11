# 継続検証: local/mock lifecycle

2026-10-11の公開baselineに対する追加実装です。実AP・実provider・新secret・新OAuth grantを使わず、固定public cmdbox 0.8.5.4の独立コピーと実Redis・ADK 2.8.0で検証します。既存AP、既存volume、Dockerの全体設定、停止済み内部HTTP試験は変更していません。

## 完成した範囲

| 優先項目 | 実装と確認した経路 |
|---|---|
| 設定/schema/bootstrap | `static_api_key`と`user_ap_binding`を明示。混在・暗黙mode・delegated fallback・空key・wildcardを拒否。UID modeは署名issuer、verifier、broker、同一shared Redis guardが必須。native workerは設定をADK開始前に検証 |
| 接続UI相当のlifecycle | native password loginのserver UID/sessionからfake start/callback/refresh/revoke APIへ。stateはsession・UID・120秒TTL・開始generationに結合し一度だけ消費。S256 verifierはserver側、返却はchallengeのみ。fake subject/project/grantを固定manifestと照合 |
| refresh/revoke/cache | fake vaultとbindingを同一SQLite transactionで更新。refreshの期待generationを使い競合を一回に集約。失敗はtoken削除・generation増加・再接続要求。worker preflightが期限切れを更新。実ADK cached toolの旧generation/別UIDを拒否し、処理中revoke後の戻り値も破棄 |
| 複数Web/worker | localhost 18090/18092に別Python processを起動し、各processのnative workerが専用Redis queueを消費。nonce counterとSET NX EX replay guardは共有。同じsigned jobの成功は一回、期限切れjobは拒否。同chat IDでもhistory/tool/binding/artifactはUID別 |
| 旧username履歴移行 | 実ADK2.8 SQLiteで合成旧名を安定UIDへ移行。session/event/user stateをtransactionで更新。曖昧mapping・既存UID衝突を拒否。元DB backupと移行後fingerprintを保存し、追加作業があればrollbackを拒否。表示名renameはownerを変更しない |
| 標準API棚卸し/認可 | 固定public sourceの123 literal route宣言・17 agent commandをAST棚卸し。native session_list/history/session_delはWeb署名job→Redis→標準workerを実行。unsigned resource jobは拒否。native users/groups readはdummy admin roleで制限。実ADK FileArtifactServiceの読取りはserver選択UID rootのみ。その他管理/汎用exec/filer/key発行routeはmountしない |

設定契約は[JSON schema](tool-config.schema.json)と`poc/cmdbox_gateway/config.py`、literal routeとagent commandの適用範囲は[棚卸しJSON](native-api-inventory.json)にあります。動的asset routeや追加extensionのruntime登録は123件に含みません。公開patchはWeb agent、AgentChat、SessionList、SessionDelの4ファイルです。元の固定source checkoutは変更しません。暗黙の既存MCP設定はこのpatchでは拒否されるため、明示modeへの設定変更が必要です。

static経路はnative config/header構築と実ADK Runner/tool実行を通ります。LOCAL MOCKではMCPToolset factoryをin-process dummyへ差し替えます。実static MCP socket/remote serverを検証した結果ではありません。

## 再現と検証

専用runtimeと独立public copyはREADMEのsetupで準備し、既存の専用Redis composeだけを使用します。既存listenerがあればtest harnessは上書き・停止せず拒否します。

```powershell
docker compose -f app-lab/compose.yml -p cmdbox-ap-lab-mock up -d
.\runtimes\python312\python.exe -X utf8 poc\run_mock_tests.py
.\runtimes\python312\python.exe -X utf8 app-lab\test_app_path.py
.\runtimes\python312\python.exe -X utf8 app-lab\test_continuation.py
.\runtimes\python312\python.exe -X utf8 tools\check_public_patch.py
```

offline32 unit/integration + 実ADK7、既存実アプリ11、継続12 scenario groupが通過しました。継続12には両Web/workerのtrace、tool allowlist、禁止socket試行ゼロ、所有processの正常終了の照合を含みます。[集約JSON](continuation-summary.json)に適用範囲を記録しています。生trace・DB・backupはignored領域に保持します。

39件は旧unit/integration28件＋新しい設定4件＋旧実ADK dummy7件です。11件はbaselineの同じ実アプリ試験を最終codeで再実行したもの、12件は新しい継続シナリオ群です。UID分離・generation・cache等の観点は重複するため、合計62を独立した新規検証62件とは扱いません。前段の実ADK＋実AP8件は今回の39/11/12に含めず、再実行していません。

任意のcorrectness lintはofficial PyPIのRuff 0.14.0をhash固定で取得し、専用runtime内だけへ配置します。

```powershell
.\runtimes\python312\python.exe -m pip install --index-url https://pypi.org/simple --require-hashes --no-deps --target runtimes/lint-deps --cache-dir runtimes/pip-cache -r lint-requirements.lock
.\runtimes\python312\python.exe -X utf8 tools\lint_public.py
.\runtimes\python312\python.exe -X utf8 tools\scan_public_candidate.py
```

lintはpublic candidateのみを対象にAST・Ruff correctness・差分の空白を確認します。unified diffの空context行は形式上のspaceを含むため、patch自体の追加source空白は`git apply --check --whitespace=error`で確認します。固定sourceへのpatch replayと独立copyとの一致も検査します。既存の専用runtime以外を使う場合、`CMDBOX_LAB_RUNTIME_ROOT`をsetupと実行で揃えてください。

## 未検証と実AP統合の条件

- fake state/PKCE/token/password/cookie/signing keyは公開literalです。本番の安全なentropy、TLS/session設定、暗号化vault、provider refresh token rotation/revoke失敗再試行は未実装です。SQLite transaction内のfake呼出しを実provider HTTPへそのまま置き換えてはいけません。
- 新adapterと実AP CE0.92.2は未接続です。対象AP/project/client/scope/本人/用途を明示した新grantの許可後に、公式OAuth metadata・redirect・実PKCE・userinfo subject・project/grantを照合し、認可済みflowとConnectionで統合する必要があります。
- 実AP/Google Drive/SlackのConnection、token、実データ、flow配布や公開は未検証です。対象account/workspace/app/scope/保管先/失効手順を親で確定してから進めます。
- history移行は合成データの固定ADK2.8 schemaだけです。実履歴、旧filesystem artifact、別schema、稼働中のonline移行には適用していません。server/workerを停止し、本人確認済みmapping、backup、保管・rollback方針を決める必要があります。
- 全標準管理UIやupstream全APIのACLを保証する結果ではありません。棚卸しの未mount群を実運用で有効化する際には個別にUID/role/path/command認可が必要です。汎用MCP proxyは追加していません。
- static-only Web bootstrapは未検証です。今回のlabはstatic/UID両modeと全identity runtimeを注入しています。tool層のstatic-only設定検証はUID broker等を要求せず成功しますが、native Web jobには署名issuer、worker verifier/shared guardが必要です。Web/CLIのruntime roleを区別して不足依存を起動時に拒否する一般化したbootstrapは未整備です。

## 作業保全とレビュー

初期状態は指定main baselineと一致しcleanでした。作業branchを作成し、mainを保全しています。最初の一括適用はauto-reviewが「既存fileの上書き前に全対象rollbackがない」として拒否したため、全対象のhash付き復元copyを先に作り、個別編集として再承認・適用しました。その後の修正も元fileをbackupしてから適用しています。既存workspaceの置換や削除は行っていません。

追加push/PRは行いません。親の確認前のcode/data公開はありません。独自lab licenseは未選択のまま、上流noticeは維持します。pattern scanは全secretを検知する保証ではないため、差分の目視確認も必要です。
