# 実装エージェント向け参照

これは固定公開cmdboxの独立patch copyを使うlabであり、非公開アプリの移植済み実装ではない。まず[概念](CONCEPTS.md)、[役割](RESPONSIBILITIES.md)、[実測](GOOGLE-DRIVE-E2E.md)を読み、次に下記の責務単位を参照する。自然言語LLMの自律選択は未検証。

## ソースの入口と契約

| 入口 | 責務・維持する契約 |
|---|---|
| [patch](../patches/cmdbox-uid-gateway.diff) | 固定上流のWeb agent/AgentChat/SessionList/SessionDelの4ファイルだけを独立copyへ適用。元sourceを変更しない |
| [core.py](../poc/cmdbox_gateway/core.py) | checked login UID、署名job、TTL/nonce/digest、共有replay guard、binding/generation、返却前の再照合 |
| [config.py](../poc/cmdbox_gateway/config.py) / [schema](tool-config.schema.json) | static API-key共通経路とuser_ap_bindingを明示分離。混合credential/未注入bootstrapをfail closed |
| [integration.py](../poc/cmdbox_gateway/integration.py) | 実invocation scopeとworker bootstrap。APIkey経路へ黙ってfallbackしない |
| [adk_adapter.py](../poc/cmdbox_gateway/adk_adapter.py) / [drive_adk.py](../poc/cmdbox_gateway/drive_adk.py) | UID別toolset、cached toolの主体/世代確認。通常toolは承認alias一つ |
| [oauth_live.py](../poc/cmdbox_gateway/oauth_live.py) | 固定issuer/resource、public client/S256、metadata、userinfo、同tokenのsubject/project/client/grant検証。任意URLをmodelから受けない |
| [lifecycle_live.py](../poc/cmdbox_gateway/lifecycle_live.py) | pending state/session、lease/CAS、refresh競合、revoke、generation失効。network中にSQLite write transactionを保持しない |
| [vault_live.py](../poc/cmdbox_gateway/vault_live.py) | owner-only rootとCurrentUser DPAPI。これはlocal labの保管でproduction secret managerではない |
| [stock_drive.py](../poc/cmdbox_gateway/stock_drive.py) | 固定UID/subject/project/flow/Connection/published版/receiptを照合。receipt SHAはowner設定の一致でAP署名付きattestationではない |
| [stock_mcp.py](../poc/cmdbox_gateway/stock_mcp.py) / [mcp_live.py](../poc/cmdbox_gateway/mcp_live.py) | 公式SDK・新session・固定raw名・空引数。既知response wrapper一つだけを解く |
| [drive_search.py](../poc/cmdbox_gateway/drive_search.py) | 最大20行/最小id-name-mimeType。file namesを命令として扱わない。stock取得量の上限ではない |
| [live_launcher.py](../app-lab/live_launcher.py) / [live_app.py](../app-lab/live_app.py) | native Web/Redis/worker/実ADKへ接続。fresh owner-approved bootstrap、private settings、通常allowlistを維持 |
| [stock_retention.py](../poc/cmdbox_gateway/stock_retention.py) / [cleanup_live.py](../poc/cmdbox_gateway/cleanup_live.py) | local token purgeとhistory read-only保持。HTTP200、AP grant、Connection、provider grantの終了を別判定 |
| [migrate_synthetic_history.py](../app-lab/migrate_synthetic_history.py) | 合成username履歴→stable UIDの移行/衝突/rename/rollback。実履歴移行は別受入 |

private実値・実grant・provider credential・AP volumeは配布しない。公開[stock template](../templates/stock-drive-runtime.json)はdisabled/DUMMYで、そのまま実有効化するものではない。未採用custom pieceとその資料は保全案で、default suite/選択runtimeには使わない。

## 実行図

![native実行と管理MCP](images/runtime.svg)

## offlineだけの再現とchecks

PowerShell7/Git/Windowsで、固定public dependencies/sourceを初回取得する。AP/Redis/app serverを起動しないチェックは次の組合せ。

```powershell
.\Setup-ADK.ps1
.\app-lab\Setup-AppLab.ps1
.\tools\Fetch-PublicSources.ps1
.\runtimes\python312\python.exe -B -X utf8 tools\prepare_cmdbox_copy.py
.\runtimes\python312\python.exe -B -X utf8 poc\run_mock_tests.py
.\runtimes\python312\python.exe -B -X utf8 tools\check_stock_plan.py
.\runtimes\python312\python.exe -B -X utf8 tools\check_docs.py
.\runtimes\python312\python.exe -B -X utf8 tools\scan_public_candidate.py
```

lintは次の固定hash手順を使う。

```powershell
.\runtimes\python312\python.exe -X utf8 -m pip install --require-hashes --no-deps --only-binary=:all: --target runtimes/lint-deps -r lint-requirements.lock
.\runtimes\python312\python.exe -B -X utf8 tools/lint_public.py
```

[最終offline検証の集約](public-reference-checks-summary.json)を参照。check_public_patch.pyは固定sourceと独立copyの4ファイル一致を検査する。mock suiteはhttpx.MockTransport/literal sealer/scripted modelを使い、AP/Google/new grant/provider inferenceに接続しない。app起動・実資源手順は通常再現に含めない。

## 変更時の守る線

- UID/project/credential/flow/台帳をclientやLLMの入力から選ばない。接続参照とtokenはmodelへ渡さずbackendで扱う。
- raw ap_*管理toolsを通常runtimeへ混ぜない。開発は別目的/短期認可で対象flowを限定する。
- schema27のfilesはstep_1['output']。UI JSON本文とAPI dynamic wrapperを混同しない。
- 再認可で検索予算をリセットしない。trusted flow_budget_private_rootで同じ元app_budgetを使用し、今回2/2からの再起動は拒否する。
- test nameの成功から、実LLM/全UI・動的API/複数host/企業policy/Google側lifecycleへ一般化しない。
- 停止済み内部HTTP境界probeを復元/回避しない。global Docker/OS securityや他project/volumeを変更しない。
- public上流noticeを保持する。lab独自licenseは未選択で、閲覧可能であることから利用許諾を推定しない。[LICENSES](LICENSES.md)

現行codeの本番固定URL/owner-ACL制約、Google取得paging/広いscope、継続published版照合未実装、UI灰色/enable fetch根本原因未解決は[制約と残課題](NEXT-STEPS.md)にある。private helperや個人pathを公開実行手順へコピーしない。
