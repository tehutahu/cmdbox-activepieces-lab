# Phase2: 本人UIDから実APまでの限定検証結果

2026-10-11 UTC（2026-10-12 JST）、固定public cmdbox 0.8.5.4の独立patchコピー、ADK 2.8.0、AP CE 0.92.2で検証しました。新adapterのnative Web→Redis→worker→実ADK→公式MCP SDK→実APは、本人認可したA/Bの既存合成flowで成功しました。実provider credential・業務data・本番LLMは使っていません。[集約JSON](phase2-validation-summary.json)。phase2 code/資料は未公開のレビュー候補です。

## Mockと実APの区分

| 対象 | 確認した事実と限界 |
|---|---|
| phase1 local/mock | 設定schema/bootstrap、fake lifecycle、2 Web/workerの共有Redis replay/TTL、合成旧履歴移行、選択した標準API認可。実AP/OAuth/providerは使わない。[履歴](CONTINUATION.md) |
| phase2 mock | 単体回帰67件（live contract16・cleanup contract19を含む）、実ADK offline dummy7件。native mock経路4、開始UI/callback4、cleanupは3ケース・5結果群。重なる観点を独立した新機能数として合計しない |
| phase2実AP | 本人操作のAuthorizeでA/B各一回交換。AP userinfoで認証された同じtokenのsubject/project/client/grantをapproved manifestと照合。既存client/flowを使い、新client/API key/provider Connectionは作らない |
| native実経路 | 各UIDで合成flow二回がown markerのみを返し、refresh一回で同じgrantを保って世代1→2。A終了後にBを実行し、同chat名でも他UID markerなし。実APでの同時A/Bやrefresh競合を示す結果ではない |
| revoke後の拒否 | 通常revokeはHTTP200、local token参照を除去して世代3・RECONNECT_REQUIRED。native chat再要求も拒否し、flow/refresh予算は増えない。旧tokenをAPへ再送する拒否probeは行わない |
| 正式cleanup | 本人のAP USER画面の本人照合GET、filter/cursorなしの失効後一覧GET、各一ページの終端と対象active不存在を確認。既知grantに一致するFORMAL-UI-CONFIRMED二件、pending/proof/state/leaseゼロ |
| 終了処理 | 本人の専用停止・秘密削除の明示承認後、所有process/workerと二listenerを停止しport閉鎖。application秘密四件の設定file・専用signin cacheを除去し、vault旧tokenページを圧縮。audit/非secret metadata/サニタイズsummaryを保持 |

実経路のmodelは合成BaseLlmで、承認済み空引数の`lab_identity`だけを選びます。APの広い`mcp` scopeにはraw management権限が含まれ得るため、brokerは限定flow manifestをdefault-denyで守り、raw managementをLLMへ渡しません。これはAP scope自体を検索専用へ縮小した証明ではありません。

## 正式確認と秘密整理の意味

正式確認はMANUAL-AP-UI-WITNESSです。本人が実際に見たResponseと全ページのactive不存在をprivate consoleへ転記し、purpose-bound proof/CASを通してauditへ保存しました。貼り付けJSONの由来を暗号学的に証明するものではなく、自動AP USER API認証・物理AP record削除・本人に見えない全platform grantの不存在は主張しません。revoke HTTP200だけや画面の0件表示だけでcheckerを通していません。

今回のA/Bは通常revoke後に一覧が空だったため、追加grant削除や再認可は不要でした。本人AP USER Cookie/Authorization/token/HARはアプリ・親・operatorへ渡していません。[operatorの手順](CLEANUP-OPERATOR.md)。

停止後の現行vaultはtoken参照・pending/lease/cleanupなし、正式audit二件を保持し、圧縮後free pageゼロ・integrity正常です。現行専用file/DB/cache/processでapplication秘密とJWT literalの不在を確認しました。ディスク復旧領域・OS cache・本人ChromeのAP login sessionまで消去した証明ではありません。AP本体、既存client、元owner bootstrap、volume、global Docker/security、他taskは変更していません。

## ブラウザーと初期UIエラー

本人が認可とcleanupに実使用したbrowserはChromeです。事前のWindows registryでは既定handlerとして`MSEdgeHTM`を観測しましたが、その値から実際の起動browser/profileを断定しません。owner helperは`webbrowser.open`を使い、browser/profileを固定しません。

初期に本人UIエラーがありましたが、その根本原因は未確定です。後にChromeで認可と正式UI witnessまで成功したことと、原因特定は別です。browser差、CE/Enterprise制限、license、network隔離のいずれかを原因と断定していません。停止済み内部HTTP境界試験を再実行せず、以前の未分類失敗も隔離成功とは扱いません。

## 役割と残る課題

| 役割 | 完成した範囲と今後の責務 |
|---|---|
| アプリ提供者 | 既存login UIDの署名job伝搬、ADK主体、本人AP binding、限定OAuth/broker/vault、generation、local拒否、cleanup operatorと専用終了処理をlabで確認。本番UI/TLS/secret manager/運用への一般化は残る |
| 顧客管理者 | AP運用主体、利用者/project、flow配布・Connection割当・publish統制、企業provider policyと廃止/保管方針を決める。共通admin Bearerを本人権限の代わりに配布しない |
| 実ユーザー | 既存app login、本人AP account/project、本人Authorize、provider Connection認証、失効後UI確認を担当。今回確認したのは合成flow用AP認可で、Drive/Slackの本人認証は未検証 |

未完了はDrive/Slackの実Connection/provider credential・provider flow配布、production LLM、本番UID/実履歴、production vault/rotate、全標準UI/動的APIの認可です。新OAuth bootstrapは一processの二listener用session storeで、複数Web process sessionと跨host vault/leaseは未検証です。phase1の複数Web/worker mock結果で代替しません。実APでの並行refresh/revokeや負荷、static-only Webの役割別bootstrap、汎用MCP proxyも未完了です。[役割詳細](RESPONSIBILITIES.md)、[次の完成条件](NEXT-STEPS.md)。

## レビューと再現

通常再現はdummy-onlyです。`poc/run_mock_tests.py`、`app-lab/test_phase2_app.py`、`app-lab/test_live_ui.py`、`app-lab/test_cleanup_native.py`でmockを確認できます。実AP試験を再現するには別途本人の対象別承認が必要で、終了済みgrantや削除済みapplication秘密を再利用しません。

Python AST・固定Ruff correctness・空白・固定public sourceへのpatch replay、公開候補と全local Git履歴のscanを確認しました。今回の文書更新はcode/設定/環境を変えず、実試験も追加しません。raw evidence、実AP識別子、本人Response、個人path、DPAPI/DB/logはGit対象外です。phase1公開mainを保全し、phase2のcommit/push/PRは親レビュー前に行いません。
