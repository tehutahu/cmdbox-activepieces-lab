# cmdbox-activepieces-lab

追加のlocal/mock継続検証は[CONTINUATION](docs/CONTINUATION.md)にあります。設定schema/bootstrap、fake接続lifecycle、2 Web/worker、合成旧履歴移行、標準API棚卸しを実アプリ経路につないで検証しました。実AP/実providerとの新adapter統合は未実施です。

公開cmdbox、Activepieces Community Edition、Google ADKを使い、ログインUIDごとのMCP実行を検討するWindows向け検証プロジェクトです。非公開業務アプリのコードやGoogle/Slackの実credentialは含みません。

独立した合成試験として、UID adapterの35件と、実Webログイン→Redis→native cmdbox worker→実ADK→ダミーツールの11シナリオが通過しています。過去の実AP/MCP/ADK試験とは別の結果です。[検証レポート](docs/VALIDATION.md)、[設計](docs/ARCHITECTURE.md)、[残る課題](docs/NEXT-STEPS.md)、[管理者・利用者・提供者の作業](docs/RESPONSIBILITIES.md)を参照してください。

## LOCAL MOCKの再現

PowerShell 7、Git、正常稼働するDocker Desktop/Composeが必要です。初回setupは固定された公式public source/wheel/tokenizer assetを取得します。system Python、Docker Desktop全体の保存先、他projectを変更しません。CPython3.12.10の専用runtimeを再構築する方式で、既存venvをコピーしません。

```powershell
.\Setup-ADK.ps1
.\app-lab\Setup-AppLab.ps1
.\tools\Fetch-PublicSources.ps1
.\runtimes\python312\python.exe -X utf8 tools\prepare_cmdbox_copy.py

# 実AP・Redisを使わない28単体/統合 + 実ADK7シナリオ
.\runtimes\python312\python.exe -X utf8 poc\run_mock_tests.py

# 専用Redis/固定TCPプロキシだけを起動
docker compose -f app-lab/compose.yml -p cmdbox-ap-lab-mock up -d
.\runtimes\python312\python.exe -X utf8 app-lab\test_app_path.py
docker compose -f app-lab/compose.yml -p cmdbox-ap-lab-mock stop
```

Webは127.0.0.1:18090、Redisプロキシは127.0.0.1:18091です。既存listenerを勝手に停止しません。11件のtest harnessが所有Web processを起動・再起動・停止します。手動起動は`python app-lab/server.py`、停止は同じterminalへ`STOP`を入力、またはCtrl+C。最小native routeのみを使い、標準管理UI全体を検証したものではありません。

合成password、cookie ID、署名鍵は公開literalです。本番配備には使用できません。modelとMCP transportはin-process dummyで、AP/外部providerへの接続や実OAuth grantの作成は行いません。AP内部HTTP境界の停止済み試験を再実行するコードは含みません。

## ファイルと保存場所

| 対象 | 置き場とGitの扱い |
|---|---|
| コード/config template/資料/patch | このrepository、Git対象 |
| 公式Python/wheel/cache | `runtimes/`、Git対象外。projectがあるdriveに作成 |
| 公開source checkout/copy | `cmdbox/`、`app-lab/cmdbox-public/`、Git対象外 |
| 合成binding/history/raw evidence | `app-lab/data/`、`evidence/`、Git対象外 |
| Docker image/named volume | Docker Desktopの既存管理領域。repository移動で自動移動しない |
| Docker bind mount | composeを実行したcheckoutのconfig file。移転時に対象containerの再作成が必要 |

専用runtime/cacheを別folderへ置く場合は、当該terminalだけで`CMDBOX_LAB_RUNTIME_ROOT`を設定し、setupと実行で同じ値を使います。変更した場合はそのfolderの`python312/python.exe`で実行してください。個人pathや実設定をcommitしません。[保存場所と安全な移行](docs/STORAGE.md)。

## AP Docker template

`docker/compose.ap.yml`は固定0.92.2 CEとlocalhost-only ingressの未初期化templateです。新しいAP初期化ではpersistent secret/accountが必要なため、合成testの通常起動には含めません。`.env.example`に実値はなく、secretを生成するscript、OAuth callback/grant取得、実account接続、piece upload、内部HTTP試験の再実行コードは付属しません。既存APのvolume/client/grant情報もありません。

## 公開範囲・ライセンス

生ログ、private、実env、本人メール、machine名、実AP IDs、token、鍵、依存binary、大量vendoringを除外しています。結果は明示的に集約したsummaryだけを保存します。[公開候補チェック](docs/PUBLICATION.md)。

cmdbox patchの元コードはMITで、copyright/licenseを`third-party/cmdbox-LICENSE.txt`へ保持しています。ActivepiecesはCE領域のMITとEnterprise領域の別ライセンスを区別します。上流source/wheelはGitへvendorせず固定版で取得します。[上流・依存ライセンス](docs/LICENSES.md)。このlab独自コードの再配布ライセンスはまだ選択していません。公開repositoryの閲覧許可から、独自コードの利用許諾を推定しないでください。
