# Phase2 adapterの設計と認可前契約

公開phase1は `7f34def5574524a892a9b937edd2e6e64296547f`。phase2は別branchでレビューし、追加公開を確認するまでcommit/pushしません。この文書は認可前の設計・契約を記録します。その後A/Bの限定実AP試験と終了確認が完了しました。[現在の結果](PHASE2-VALIDATION.md)と[集約JSON](phase2-validation-summary.json)を参照してください。

## 実装した範囲

固定AP CE 0.92.2向けpublic-client OAuthを独立moduleに追加しました。endpoint/resource/client/対象UID・subject・project・合成flowはtrusted manifestから注入し、registrationや自動target作成を行いません。通常のtoken endpointと同じbearerを使うuserinfo検証後に、署名をAPが検証したtokenのclaimを照合します。ローカルでHS256署名を検証したと誤認しません。

state/PKCEはnative password認証済みの本人がlocal開始フォームを送った時だけ生成します。stateはUID・server session・期限・generationに結び、callbackで一度だけ消費します。SQLite lease/CASは遅いrefreshやcallbackがrevokeを復活させることを拒否します。APのrefreshが同じrefresh tokenを返してもgenerationを進め、古いtool/credentialを無効にします。各MCP呼出しは新しいSDK sessionを使い、明示された空引数の合成toolだけを実行します。

別bootstrapは既存cmdbox public sourceの独立patchコピーを使い、native password Web → 専用Redis queue → worker → 実ADK → adapterへ接続します。署名jobのUIDとADK user/sessionはphase1のpatchで照合します。外部LLMは使用せず、合成modelは `lab_identity` だけを選びます。

固定MCP serverの成功text/code block・WebhookResponse・DynamicPropertiesの一段 `response` wrapperを明示的に解釈します。汎用再帰検索は行わず、marker/owner/kindの不一致、tool欠落、upstream失敗は当該接続を停止します。実際の既存flow・membershipは本人認可後に照合します。今回のA/B既存合成flowは後続実試験で確認しましたが、別flowや他利用者への保証ではありません。

## Mockで確認したもの

| 検証 | 結果と範囲 |
|---|---|
| protocol/vault/lifecycle contract | 16 unittest成功。httpx MockTransport、public literal entropy、非暗号fixture sealer。state/PKCE、UID/session、期限、subject/project/client/scope、同refresh token、refresh競合、refresh/revoke競合、generation、cleanup、固定reply wrapper |
| native app経路 | 4 scenario成功。実cmdbox Web/password/Redis/worker/ADKと公式MCP SDK、AP/OAuth/MCPはmock。A/Bの同chat分離、refresh/revoke、trace、所有process停止 |
| 認可開始UI/callback bootstrap | 4 scenario成功。実local listener二つ、native login、単発handoff、cookie、same-origin/CSRF、mock callback、操作budget。開始前stateなし・時計未開始も確認 |

これらは24個の独立した新機能の証明ではありません。16 testと各4 scenarioには重なる経路があります。これらのmock結果単独では実APへのtoken交換・tool実行・新grant成功を示しません。実AP結果は別記録です。mock試験は実DPAPIを呼びません。

再現はpinned runtime/依存と専用Redisがある環境で、順に `poc/test_live_contract.py`、`app-lab/test_phase2_app.py`、`app-lab/test_live_ui.py` を実行します。native試験は自分のlocalhost portが空いていることを要求し、既存listenerを置換しません。結果・data・logはignored local-review/dataへ保存します。

## 明示承認されたlocal実試験の準備契約

実利用はdefault起動しません。専用G private rootを新規作成し、CurrentUser+SYSTEMだけの保護ACLを確認した後、application job/session keyと合成native login passwordをCurrentUser DPAPIで保管します。AP client secret/API keyは生成しません。本人がowner helperを実行するとnative local login後の30秒単発handoffをブラウザで開きます。このhelperはAP Authorizeを押さず、state/PKCEを事前生成しません。

本人の開始フォームから最長2時間の共有時計を開始し、A/B各一回のcode exchange、一回のrefresh、本人合成flow二回までに制限します。callback/listenerは同一server session storeを共有します。初回起動時のAP通信は通常の公開metadata GET二つだけです。未認可・全状態が空の既存準備だけを再開する `--resume-pre-authorize` は既存秘密を再利用し、AP通信を行いません。旧client/対象が無効なら停止し、新registration・flow作成へ進みません。

期限/停止時はauthorityを先に無効化し、通常revokeを試み、application秘密を除去して専用listener/workerを停止します。revoke HTTP200は正式失効確認ではありません。別途本人のAP USER権限/UIで対象grantの失効を確認するまで暗号化cleanup recordは保留します。token交換の結果が不明な時も、grantなしと断定しません。未確認cleanupは追加接続を拒否します。本人UI operatorは対象IDを削除前に照合し、全ページactive不存在の本人証言をpurpose-bound proofとして消費します。確認失敗・交換後identity不一致は全UIDを停止します。期限後も最小の暗号化cleanup設定で処理できます。

## 未検証・適用限界

後続実試験で新adapter＋実AP、既存client、A/B subject/project/grant、既存合成flowを確認し、各UIDのrefresh・通常revoke・ローカル拒否を通しました。[本人UI cleanup operator](CLEANUP-OPERATOR.md)で二対象のactive不存在を本人UI witnessとして確認し、専用停止・秘密整理も完了しています。通常metadataやrevoke HTTP200だけで正式確認したという意味ではなく、自動AP USER API認証経路は提供しません。実Google Drive/Slack/provider credential、本番LLM、本番vault/rotate、production UID/history、multi-hostは未完了です。

新bootstrapのsession storeは同一processの二listener用です。別Web processへのsession共有や別host間vault leaseは完成していません。phase1の複数Web/worker・共有Redis replay検証と混同しません。static-only Web bootstrapの役割別依存、全動的route/admin認可、実旧履歴移行、汎用MCP passthroughも未完了のままです。

停止済み内部HTTP境界試験を再実行する機能・代替経路は追加しません。既存AP/owner bootstrap/client/volume、global Docker/security設定は変更しません。private設定・識別子・token・raw logは公開candidateに含めません。
