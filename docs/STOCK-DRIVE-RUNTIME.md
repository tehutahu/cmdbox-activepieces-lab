# stock Google Drive を選んだローカル実装

最新：[2026-10-12 E2E](GOOGLE-DRIVE-E2E.md)で標準中継・実2件・終了を確認済み。以下のlocal/mockは先行する別の根拠で、実LLM/production完成とはしません。

選択は標準 Google Drive piece、本人の通常 Google account、広い `drive` scope。custom piece の22ファイルと前段の実AP終了証跡は保全した未適用案であり、今回の本番経路には登録しない。公開npm/private archive/別AP instanceへの導入を進めない。

## 実アプリの入口

`app-lab/live_launcher.py` → `live_app.create_apps` → 共通 `integration.bootstrap` → 標準cmdbox Web login/Redis job/worker/実ADK/公式MCP SDKの経路に `lab_drive_search` を登録した。toolset factoryの置換で試験を成立させない。static key共通toolは従来の明示設定、UID経路は `lab_identity` または `lab_drive_search` 一つだけ。別aliasのbroker、混合credential設定、memory replay guardはbootstrapで拒否する。

`stock_drive.py` は protected settingsの `stock_drive` manifest、`stock_flow_receipts`、既存UIDとAP subject/project/flow/Connection/版の対応を照合する。disabled公開template、DUMMY実対象、重複UID/flow、入力可変化、ローカルreceiptのdigest不一致は有効化しない。brokerは現在のbindingと署名済み実ADK contextを再照合し、呼出し前・返却後にgenerationと期限を検査する。MCP discoveryも固定raw名と空引数schemaだけを受け入れる。

manifestは所有者管理のcontrol-plane設定である。receiptのSHAはローカルIMPORT_FLOWの一致であり、APの現在published版を認証した証拠ではない。実適用前に所有者がproject/Connection/published版/raw名と固定検索内容をAP UIで照合し、試験中は版を変更しない。AP側を変更する前にapp bindingを停止する。継続的なpublished版照合APIは未実装。

公開 [template](../templates/stock-drive-runtime.json) はenabled=false、全step valid=false、全resource参照がDUMMY。実AP import/publish、Google Connection、grantは作成しない。単一の既存UIDはprotected `login_labels` とpassword設定に明示する。現在のnative launcherは専用lab用のserver-owned signin fixtureを用いる。既存production signin/secret provisioningを自動移植するものではない。

## stockの実際の能力と制限

固定sourceはAP CE0.92.2 `d125d34e59ac57ea4d0df57af4b917344027f06b`、Google Drive0.11.0 `drive_search_files`、MCP0.0.21、flow schema27。

| 項目 | 制御される内容 |
|---|---|
| 検索 | `name contains 'CMDBOX_LAB_ONLY'`、固定folder直下、type=file、include_team_drives=false |
| qの引用 | stockは直接文字列を埋め込む。アプリmanifestで固定ASCII値と安全なfolder IDだけを認める。stockへのescape patchなし |
| Google取得 | 1ページ1000、nextPageToken終端まで取得。総行数・ページ数にアプリ上限なし |
| trash/完全性 | stockに `trashed=false` なし。`incompleteSearch` を要求・伝播しない。返却を完全検索と表示しない |
| アプリ返却 | 最大20行、SDK text40960文字。21行以上は全体拒否。name/id/mimeTypeの3項目だけをADKへ渡す |
| 時刻等 | stock/APにはcreatedTime/modifiedTimeも返るがアプリでは捨てる。AP側run dataへの保管は別途cleanup対象 |
| 呼出し | UIDごとAP code exchange1回、app↔AP refresh1回、flow2回、全体最大2時間 |
| upstream終了 | SDK待機5秒はGoogle取得上限・AP job cancelの保証ではない。stockのGoogle retry/refreshは上記app予算の外 |

folder条件はGoogle grantの認可境界ではない。広い `drive` は全Drive fileを管理できるrestricted scopeであり、flowの読み取り用途より強い。標準auth宣言は `[drive, email]`。今回の標準Connectでdriveだけを選びemailを外して同意した。他配置で同じ選択ができなければconsent前に再レビューする。[Google scope説明](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)

## 終了・保管

stock run専用のvault/historyだけが対象。期限、operator stop、通常server終了では、新規署名発行を止めて全UIDを無効化し、通常AP revokeを試みる。成功/失敗どちらでもcleanup refresh tokenを除去し、pending/leaseをゼロ、application秘密設定を削除、callback/Webとworkerを終了する。worker停止後に専用ADK session/event/app/user stateをread-onlyで所有確認し、全行をprivate rootに保持する。所有外のapp/UID/schemaが見つかれば変更せずoperator reviewと報告する。shared Redis全体をflushしない。

run専用rootにはAP照合情報、未完了のformal cleanup記録、retention結果に加え、所有history/session/stateを保持する。HTTP200だけで正式失効済みとはしない。vault token除去にはSQLite secure_delete/VACUUMを使い、historyには適用しない。OS/cache/SSD復旧領域やChrome sessionの物理消去を保証しない。プロセスを強制kill/OS停止された場合の自動cleanupも保証しない。

Google credentialはAP Connectionに残るため、このappの2時間停止でGoogle grant/Connection/AP run dataが削除されるとはしない。[一括承認・手動終了案](STOCK-DRIVE-APPROVAL.md)で保管場所と本人操作を確認する。前段phase2 runtimeや既存AP volume/client/owner bootstrapにはこのpurgeを適用しない。

## 検証範囲

stock契約17件、選択したdefault mock96件＋実ADK dummy7件、production launcherからのnative2ケースが成功。nativeでは同chat IDのA/B、generation refresh、revoke拒否、返却最小化、期限停止、revoke失敗時のtoken除去/history全行保持を確認した。AP/Google入出力はliteral fixture、暗号はLiteralSealer、外部LLMなし。このlocal/mock自体は実Google成功の証明ではない。後続の実stock/Google/DPAPI/新AP grantはE2Eに分けた。own-client方式は未検証。custom piece試験は今回再実行せず、default suiteから除外した。

初期nginx preflightはnetworkなしの構文/配置置換だった。後続は承認済みGoogle2hostsとsecrets.activepieces.comのHTTPSだけを一時適用し、成功後に元構成/cacheへ復旧した。内部HTTP境界probeは再開していない。

次の実資源操作でもpackage/version、OAuth方式、対象、egress、保管/終了、app↔AP認可を具体承認する。標準中継の今回経路に独自GCP/clientを必須としない。停止済み内部HTTP試験は復元・再実行・別経路化しない。


## 最後の1回と元台帳

新OAuth runのprotected flow_budget_private_rootで元のowner-only SQLite app_budgetを使用し、flowを1→2へ記録した。新flow台帳への再seedはなく、初期countが1でないbootstrapを拒否する。実native経路で有効だった。元台帳は2/2、残り0。Google ConnectionはCLOUD_OAUTH2/ACTIVEで残り、AP grant/local token/Connection/Google grant/run-logの終了は別の状態として扱う。
