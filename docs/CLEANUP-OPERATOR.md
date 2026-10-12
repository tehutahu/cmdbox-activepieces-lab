# 本人UIによる正式cleanup operator

phase2のA/B実試験後、本人のChromeにあるAP USER画面から二対象のactive不存在を確認し、`FORMAL-UI-CONFIRMED` 二件を照合しました。AP USER cookie/tokenはアプリ・親・operatorへ渡していません。[結果と終了処理](PHASE2-VALIDATION.md)。これは本人UI witness方式であり、自動AP USER API認証ではありません。

## 確認の意味と境界

通常の `/revoke` HTTP200は送信済みとして記録するだけです。cleanupPendingを解除するのは、保護されたprivate rootのCurrentUser対話consoleで本人がAP UIのfresh Responseを確認し、全ページで対象active grantが存在しないことを証言した時です。`FORMAL-UI-CONFIRMED` はこの本人証言を意味し、貼り付けJSONの由来を暗号学的に証明するものではありません。自動AP USER API認証・物理record削除・本人に見えない全platform grantの不存在を主張しません。

public HTTP proof route、callerのconfirmed Boolean、LLM tool、AP USER token引数、非対話 `--yes` はありません。OS ownerがprivate manifestを復号できることと、本人が正しいAP UIを直接見たことを信頼境界とします。別USER sessionへの代理loginやtoken storage取得は行いません。

固定sourceの [Connections route](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/web/src/app/routes/mcp-server/mcp-nav.ts) は `/mcp-server/connections`、[grant table](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/web/src/app/routes/mcp-server/grants/grants-tab.tsx) はfilter/cursorを持ちます。[行操作](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/web/src/app/routes/mcp-server/grants/grants-columns.tsx) のRevokeだけを使います。UIにgrant IDは表示されないため、NetworkのGET Responseの `id` とclient/project/memberを照合します。

## 本人の操作手順

1. local connectionをrevokeするか、アプリ停止・期限到来でlocal authorityが無効になった後、専用private rootの `Cleanup-A.cmd` または `Cleanup-B.cmd` を本人のconsoleで開きます。operatorはbrowserを自動操作せず、APへ通信しません。
2. consoleが示すsubject/project/client/grantを本人だけが確認します。native label A/Bと、失敗交換で実際に取得したAP subjectが異なる場合は、consoleのAP subjectを優先します。承認範囲外のidentityは処理せず親へ戻します。
3. 既存の本人AP USER browserで `http://localhost:18088/mcp-server/connections` を開きます。正しい本人表示を確認し、filterとcursorをclearしてreloadします。
4. Networkで本人照合用GET `/api/v1/users/<subject>` のRequest URL、HTTP200、Responseの `id` を確認します。consoleにはそのResponseから `{"id":"画面で確認した値"}` のみを転記し、単独行 `END` で終えます。別人の管理者取得結果を本人照合に使いません。
5. 対象がactive、またはgrant IDがUNKNOWNなら、削除前のGET `/api/v1/mcp-oauth/grants` のRequest URLとResponse JSONを入力します。最初のURLにcursorはなく、queryはcursor/limitだけです。`next` がnullになるまでUIでページを進め、各ページを入力します。HTTP200以外・filter付き・欠落ページ・循環cursorは正式確認になりません。
6. operatorが削除対象IDを検証・表示してから、そのID・client/project/memberに対応する1行だけの Revoke → Revoke access → Revoke を本人が実行します。全選択・複数行Revokeは使いません。UNKNOWNは今回の交換時刻に対応する一意な行だけが対象です。0件・複数件・対象不一致では削除案内に進まず停止します。
7. fresh reload後、filter/cursorなしの一覧を再び最終ページまで入力します。通常revokeで既に消えている既知IDの場合も、この削除後全ページ確認は必須です。
8. 本人session・正しいorigin・HTTP200・fresh reload・全ページを直接確認した場合だけ、consoleに表示された `AP-UI <subject>` を入力します。成功時のsummaryだけを親へ返し、private IDやResponse全体は送らないでください。

転記するのはResponse JSONとRequest URLだけです。Request headers、Cookie、Authorization、HAR、Copy as cURL、token、password、loginデータは渡しません。入力のcredentialらしいkey/valueも拒否します。

## 失敗・期限・保持

正式確認の失敗・本人consoleのCtrl+C中断は全UIDのrecordを一つのSQLite transactionでRECONNECT_REQUIREDにし、token参照・pending state・leaseを無効化します。ネットワークrevokeより前に停止フラグが立ち、native watcherが専用listener/workerを止めます。確認できていない暗号化cleanupは保持します。無効なstateだけでは全UID停止を誘発しませんが、交換後の不明・不一致identityは追加認可を止めます。

proofはpurpose binding、UID、generation、対象cleanup cipher digest、確認時刻、5分期限に結び、CASで一度だけ消費します。consoleとruntime watcherの同時消費は同じ暗号化auditがある場合だけ冪等です。古い・破損proofはcleanupを解除しません。quarantineは後からcleanupが成功しても解除せず、新しい認可には親への再確認が必要です。

共有2時間期限または専用stop-request時は全UIDを先に停止し、通常revokeを試みます。application password/job/session keyの `settings.dpapi` は除去し、本人DPAPIで暗号化した `cleanup-settings.dpapi` に非secret設定・照合対象だけを残します。refresh等が必要な未処理cleanupは暗号化vault内に残るため、後片付け完了までrootを消しません。operatorは期限後もこの最小設定で使えます。

UNKNOWNの0件・複数件・時刻不整合、承認外identity、本人の全ページ一覧を確認できない場合は、grantなしと断定しません。通常revoke失敗でも対象1行をUIで削除し、その後の全ページ確認ができれば処理できます。判断不能なら停止を維持して対象・追加認可範囲を親へ戻します。

## 検証範囲

`poc/test_cleanup_contract.py` はmock19ケースで、target事前照合、本人、全ページ、hidden second page、credential拒否、未知grant、通常revoke失敗、stale/corrupt/期限proof、同時消費、非対話拒否、全UID停止を確認します。

`app-lab/test_cleanup_native.py` は実cmdbox native Web/password、専用Redis/worker、実ADK、公式MCP SDKを使い、AP/OAuth/UI Responseはmockです。正常cleanup、revoke/UI確認失敗後の停止と期限後復旧、wrong AP subject callbackの停止を確認します。fake clockで2時間到来を進め、所有listener/heartbeat/signin cacheの撤去、application key file除去、最小cleanup設定、停止後の本人console処理まで通します。

mockはliteral sealer/entropyを使い、DPAPI暗号・実AP USER session・実AP grant失効を検証しません。CurrentUser DPAPI/owner ACLはlocal準備で別に検証し、その後A/B実APに対して本人照合GETと失効後grants GETの実Response・全ページ・明示本人確認を使いました。二件の暗号化auditは既知grantと一致し、cleanup/pending/proof/leaseはゼロになりました。停止済み内部HTTP境界試験は含みません。

今回の二対象は通常revoke後の一覧が空で、実Responseの終端も確認できたため、削除前一覧や追加Revokeを行わず既知grantの失効後確認だけで完了しました。画面の「0件」表示や親が既知のsubjectからJSONを作る操作ではcheckerを通していません。

Chromeの具体的操作はF12→Network→Fetch/XHR→再読み込み、本人users GETとgrants GETを選び、GeneralのRequest URL/200とResponseを確認する順です。既定browserのregistry観測は実際の起動browser/profileを証明せず、helperもprofileを固定しません。確認できない応答は推測して転記しません。

専用停止・秘密削除は本人の明示承認後に行い、application設定fileと専用signin cacheを除去し、vaultの旧tokenページを圧縮しました。正式auditと照合metadataは保持しています。現行file/DB/cache/processの確認であり、ディスク復旧領域・OS cache・本人Chrome AP sessionの消去証明ではありません。
