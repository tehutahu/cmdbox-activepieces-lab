# cmdbox / Activepieces / ADK 検証の受渡し

この文書の本文は公開baseline時点の履歴です。最新の[phase2結果](PHASE2-VALIDATION.md)では新adapter＋実APのA/B合成flow、refresh/revoke、本人UI witness二件、専用停止・秘密整理まで確認しました。本文の「未実装/未接続」はその当時の状態です。現在の役割分担は[RESPONSIBILITIES](RESPONSIBILITIES.md)、残課題は[NEXT-STEPS](NEXT-STEPS.md)、集約値は[最新JSON](phase2-validation-summary.json)を参照してください。

これは公開candidateと共有資料に使えるサニタイズ済み文章です。本人メール、実AP識別子、machine名、個人path、secret、生ログは含めていません。

## 全体の結論

既存ログインUIDを持つcmdbox系アプリに対し、APをユーザー別Connection/flow実行基盤として利用する案は、CE0.92.2の合成flowで検証できました。APがDrive/Slack credentialを保管しても、アプリUIDと本人AP subject/project/grantの対応、AP access/refresh lifecycle、許可toolの制御はアプリまたは独立brokerに残ります。共通管理者Bearerを全利用者へ流用する設計は推奨しません。

本検証のAP flow-to-toolは、AP Connection/pieceでflowを作ってMCP toolにする方式です。任意の公開MCP serverをdiscovery/auth/sessionごと透過中継する汎用proxyを実装した結果ではありません。

## 実施済みと未実施の区別

| stage | 結果と限界 |
|---|---|
| 実AP CE0.92.2 | 2人の別MEMBER/personal project、本人project-scoped MCP認可、通常discovery/callの合成markerと他project拒否を確認 |
| flow配布 | ownerの正規USER sessionでimport/validate/publishと再実行差分ゼロ。合成templateに限る。CE service API key/SSO/embeddingは同じ証拠で利用可と判断できない |
| 実ADK＋実AP | 当時有効な本人grantで8シナリオ通過。app UIDは合成で、cmdboxの実ログインには未接続 |
| 新UID adapter | 28 unit/integration＋実ADK7、計35件通過。署名/TTL/replay/UID/session/generation/cache/allowlistをdummy-onlyで検証 |
| cmdbox実アプリLOCAL MOCK | native Web password route→実Redis→native worker→実ADK→dummy toolの11件通過。同chat IDのA/B履歴分離、UID指定拒否、未接続C、A切断後B継続、再起動後state保持を確認 |
| grant終了 | 対象2grantを正規revoke API成功＋有効metadata不存在で失効確認、local token削除。旧token拒否probeは未実施 |
| 未実施 | Drive/Slack実credential接続、新adapterと実APの実統合、本番認証、既存全UI/APIの隔離、汎用外部MCP proxy |

AP本人project tokenでも42のraw management toolsが見えました。mcp scopeを検索専用権限と見なさず、brokerでdefault-denyと承認flow manifestを使う必要があります。

外側Webhook ingressの拒否とAP内部実行は別境界です。過去に内部匿名Webhookから合成flowが動作しました。追加の内部HTTP試験は未分類失敗でHTTP statusを得られず、停止指示により終了しました。隔離成功・迂回成功とは判断せず、再実行や別経路debugの機能をpublic candidateへ含めません。

LOCAL MOCKのpassword/cookie/署名鍵は公開literalです。model、MCP transport、credential providerはin-process dummy。11件の成功はUID伝搬とnamespace分離を示し、本番認証や実AP接続の完成を示しません。

## 役割ごとの必要作業

## 導入企業の管理者

| 作業 | 状態・注意 |
|---|---|
| AP運用主体を決める | 自社運用かアプリ提供者運用かを選ぶ。credential/data/backupの責任主体、障害・退職時の窓口を決める |
| 自社運用の場合のAP基盤 | CE版とimageを固定し、HTTPS、認証、公開経路、backup、更新、監査、接続暗号化keyの管理を行う。local PoC設定を本番へ流用しない |
| AP利用者とproject | 利用者のaccount/招待とpersonal projectの運用を用意する。今回の2利用者で別projectを確認。CE user-limit bypassは固定版sourceで確認、負荷や将来版の保証ではない |
| flowの配布 | 合成templateをownerの正規USER sessionで各projectへimport/validate/publishする自動化と、再実行差分ゼロを確認。管理UIの正規APIを使う限定検証であり、CEのservice API keyや安定API契約を実証していない |
| Connection割当と許可flow管理 | ユーザーConnectionをどのflowが使うか、公開する読取tool、変更/publishの統制を決める。実Drive/Slack flowの配布と割当は未検証 |
| Google Workspace / Slack方針 | OAuth app、scope、workspace app install、user/bot権限、企業の制限に応じて審査・設定が必要かを確認する。企業管理者承認が全環境で一律必須とは未検証のため断言しない |
| 利用終了 | account/project/Connection/grantの廃止、broker binding停止、data保管方針を合わせる。今回の対象MCP grantは正式失効、旧token拒否probeは未実施 |

自社運用を選ぶ場合でも、アプリ側のUID/OAuth/broker実装はアプリ提供者の作業です。管理者が共通tokenを配布して代替するものではありません。

## 実際の利用者

初回は次の流れを想定します。以下のうち実Drive/Slack認証やアプリ内接続UIは設計上の必要手順で、実装済みとして扱いません。

1. アプリの既存ログインを使う。UIDはserver側で確定する。
2. APの自分のaccount/personal projectを利用できる状態にする。招待が必要な運用なら管理者から受ける。
3. 配布されたflowを確認する。未配布ならtemplateから作成する運用が候補。合成flowの管理者配布は自動化済みだが、実provider用flowの利用者負担を完全に自動化した結果ではない。
4. AP Connectionで自分に許されたDrive/Slack accountを認証し、flowへ割り当てる。APにcredentialを持たせる候補構成。実providerでは未検証。Slackのbot Connectionならproject分離だけで人別の閲覧権限になるとは限らないため、権限modelを別途確認する。
5. アプリの接続操作から、本人がAPのproject-scoped MCP認可を行う。AP単体での本人認可は検証済み。アプリcallback/state/PKCEと本人bindingの実統合は未実装。
6. 接続結果を確認してchatを使う。失効・権限変更・期限切れで再接続が必要なら本人が再認可する。dummyでは未接続/切断をreconnect_requiredで停止できた。

管理者がtemplate配布を自動化しても、本人によるprovider Connection認証と本人AP MCP認可は別の操作として残ります。実際のcredential/grantを本人の同意なしに代理取得する自動化は検証していません。

## アプリ提供者

| 実装・設定 | 現状 |
|---|---|
| 安定UID伝搬 | 公開cmdboxコピーでchecked server session→署名Redis job→worker検証を実装。表示名やclient/LLM指定から主体を選ばない |
| ADK主体の統一 | session/run/artifactをUID namespaceへ。実ADKと同一chat IDのA/B分離を確認。既存履歴移行と全標準APIのACL点検は残る |
| 本人binding | UID/AP subject/project/grant/credential参照/generation/status。dummy-only SQLite保存を実装。本物のbindingの制御面は未実装 |
| AP OAuth client/接続UI | state/PKCE、redirect、本人subject/project/grant照合、接続・失効UIを実装する必要がある。新adapterでは未実装 |
| token broker/vault | AP access/refresh tokenの安全な保管、refresh/revoke、generation/cache破棄を実装する必要がある。アプリ本体には参照だけを持たせ、別brokerへ保管を寄せる案 |
| tool権限 | raw management toolsをLLMへ渡さずdefault-denyと承認済みflow manifestを使う。dummyではdiscovery/execution/戻り値の世代を再検証。実APとの接続は次段階 |
| 本番認証と基盤 | 公開literal password/cookie/keyを置き換える。TLS/session設定、process分離、Redis ACL、secret保管、監査を実装・検証する |
| APを提供者が運用する場合 | AP基盤、backup、更新、暗号化key、監査、tenant/project設定、障害対応も提供者の責務になる。導入企業の利用許可・provider権限方針は別途調整 |

## AP運用主体で変わる責務

| 対象 | 導入企業がAPを運用 | アプリ提供者がAPを運用 |
|---|---|---|
| AP infrastructure/backup/update | 導入企業が主担当 | アプリ提供者が主担当 |
| AP credential暗号化keyとdata保管 | 導入企業の管理下 | 提供者の管理下。契約・保管境界を明示 |
| provider app/scope/利用許可 | 導入企業の方針に合わせて調整 | 同じく導入企業の方針に合わせて調整 |
| 利用者の初回本人認証 | 利用者。管理者は招待/templateを支援 | 利用者。提供者は接続UI/templateを支援 |
| アプリUIDと本人APの対応 | アプリ提供者の実装＋企業の運用 | アプリ提供者の実装・運用 |
| AP token lifecycle | アプリまたは独立brokerの責任主体を合意 | 提供者brokerを候補。企業ごとの境界も必要 |

## 単純MCP proxyとの違い

単純proxyは外部MCPのdiscovery/call/auth/sessionを中継します。本PoCはAP Connectionとpieceを使うflowを作り、そのflowをMCP toolにします。管理者がflowを配布し、利用者がConnectionを割り当て、brokerが承認flowだけを呼ぶ構成です。外部公開MCPを任意にそのまま接続できる汎用proxyを実装した結果ではありません。

CE0.92.2の検証結果は固定版・合成dataに限ります。SSO/embedding/service API keyの有料境界、実providerのOAuth app設定、企業ポリシー、他版の挙動を一括して解決したものではありません。次の段階で対象を分けて確認します。


# 次の課題と完成条件

project化・移行・公開candidate確認・レポートを先に完了し、その後に次の検証へ進みます。新しいsessionは整理のためだけに使い、過去の停止や安全判定を回避しません。

## 既存権限で進められるlocal/mock作業

| 作業 | 完成条件 |
|---|---|
| 設定schemaとbootstrap | static API-key経路とuser binding経路を明示区分し、必須runtime未注入でfail closedする。合成設定で動作確認 |
| 複数Web/worker | 別process間でも署名job/TTL/shared replay guardが有効で、並行A/Bのcached toolが越境しない |
| UID履歴移行 | 合成旧username履歴から安定UIDへ移行し、表示名変更/衝突/rollbackと他UID読取拒否を確認 |
| 標準UI/APIの隔離 | dummy-only構成で全history/session/artifact/admin routeを棚卸しし、認可の完成条件とnegative testを作る |
| AP CE契約のsource点検 | 固定版のschema/有料境界とtemplate仕様を記録する。実account/credential/grantを新規作成しない |
| lifecycle contractの合成検証 | state/PKCE/refresh競合/revoke/cache破棄をfake provider/vaultで確認する。実tokenは使わない |

## 本人の新認可・対象別承認が必要な作業

| 作業 | 承認対象と完成条件 |
|---|---|
| 新adapter＋実AP接続 | 対象AP、project、client、scope、本人、用途を明示して新grantを許可。subject/project/grant一致と限定tool実行を確認し、終了処理も定義 |
| 本番用secret/vault | 鍵/API keyの発行対象、保管先、権限、利用範囲を明示。dummy literalを除去し、安全な保管・rotate・失効を確認 |
| Google Drive実接続 | 対象test account、OAuth app/scope、読取対象を明示。企業policyを確認し、本人Connectionと検索権限の差を検証 |
| Slack実接続 | 対象workspace/test account、app/scope、user/bot方式とchannel範囲を明示。人別の閲覧境界と企業policyを検証 |
| 実flow配布 | approved template/Connection割当とoperator権限を定義。idempotencyとpublish変更統制を検証 |

企業管理者承認の要否はGoogle Workspace/Slackのpolicy・app・scopeで異なる可能性があり、一律必須と未検証のまま断言しません。

## 安全停止により再開しないもの

停止済み内部HTTP追加試験、別network/loopback経路による同試験のdebug/retry、停止を避けるsession変更は実施しません。公開codeにも再実行機能を含めません。未分類失敗を隔離成功・迂回成功と扱いません。Docker/securityの全体設定緩和、他project停止、volume削除、公開tunnel等もこの継続作業に含めません。

任意外部公開MCP passthroughはAP flow-to-toolとは別の未実装機能です。後続で必要性と認可/session設計を分けて検討します。


## 継続用projectと保存場所

継続projectはコード、patch、固定hash lock、Docker/config template、test、設計/検証/責務/残課題/上流licenseを保持します。上流source本体、wheel、venv、実env、client/grant/token、生ログ、停止試験codeはGit対象外です。public sourceは固定commitから再取得し、専用runtimeは新置き場で再構築する方式です。

Docker image/volumeは既存Docker Desktop管理領域のまま保持します。host bind mount、Python/cache、SQLite履歴とは別の保存先です。code移転でDocker diskを移動せず、移行対象の専用mock containerだけを扱います。原clone、旧証跡、既存AP volumeは保持します。

独自lab codeのlicenseは未選択なので、無断で新たな利用許諾を付与しません。cmdbox patch元のMIT noticeを保持し、APのCE/Enterprise境界、ADKとPython依存の宣言licenseを区別します。依存binaryやpiece packageはvendorしません。

外部repo作成/pushは公開candidateの最終確認後です。新しい検証はproject化・移行・再現・レポート完了後に進め、本人の新grantやprovider接続が必要な作業は対象別に承認を得ます。
