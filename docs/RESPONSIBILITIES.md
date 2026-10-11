# 誰が何を準備・実装するか

## 結論

APを「ユーザー別のConnectionを持つflow実行基盤」として利用する案は、CE0.92.2の合成flowと本人認可で検証できました。APがDrive/Slack credentialを保持しても、アプリUIDと本人AP subject/project/grantの対応、AP token lifecycle、許可toolの制御は残ります。共通の管理者Bearerを全利用者へ流用する設計は推奨しません。

現時点で成功したものは、過去の実APの個人project・本人MCP認可・合成flow配布・通常APIのproject境界、実ADK＋実APの8シナリオ、新UID adapterの35件、実cmdbox Web/Redis/ADKのdummy経路11シナリオです。Drive/Slack実接続と新adapter＋実APの接続は未実施です。内部HTTP境界は未解決の試験を停止しており、再実行codeを公開candidateへ入れていません。

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
