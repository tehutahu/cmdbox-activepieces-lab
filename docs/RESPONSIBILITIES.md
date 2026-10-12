# 顧客管理者・実ユーザー・提供側の作業

2026-10-12、標準Google Driveの本人認可と、既存UIDからnative cmdbox → Redis → worker → 実ADK scripted → AP標準flow → metadata2件を確認した。AP標準OAuth中継の成功経路では顧客独自GCP clientをAPへ登録していない。[検証結果と限界](GOOGLE-DRIVE-E2E.md)

## 最初に決めること

APを顧客が運用するか、我々が運用するかを決める。APは利用者別Connectionとflowの基盤。アプリUIDとの対応、本人AP認可、token lifecycle、通常tool制限は我々の実装に残る。固定公開cmdboxの独立copyによる限定lab検証であり、既存業務アプリ全体へ移植済みという結果ではない。

## 顧客側の管理者

| 必要な作業 | 標準中継での担当 | 選択肢・未検証 |
|---|---|---|
| 利用方針 | app/scope、許可データ、保管期間、外部中継の利用可否を決める。driveは広いscope | 顧客専用appが必要なら管理主体・審査・key管理を我々と合意 |
| 組織のOAuth許可 | Workspace等のpolicyで必要ならAP側Google app/scopeを審査・許可 | 個人account成功を企業許可と扱わない。管理者承認は全環境で一律必須ではない |
| AP account/project | 招待、利用者/project対応、Connection所有者、共有project/tenant境界を確認 | GCPを作るだけではAP/app UID隔離は完成しない |
| flowの統制 | 我々のreviewed templateとConnection割当を採用し、編集/Publish担当を決める | 元flowのMCP読取/有効化は確認。多数顧客への自動配布は未検証 |
| APを顧客が運用 | TLS、backup、暗号化key、更新、監査、networkを主担当 | 我々が運用するなら我々の責務。顧客の利用/認証policyは残る |
| 終了・退職・障害 | app binding、AP grant、Connection、provider grant、履歴の終了/保管方針を決める | Connection削除とGoogle revokeを別確認 |

標準中継のこの経路では、管理者が利用者ごとにGCP project・Google client ID/secretを発行する作業は必須でない。Google appの管理はAP側にあり、scope・組織許可・通信・保管の判断は顧客にも残る。企業policyそのものを今回の個人Google accountで実証したわけではない。

## 実ユーザー

1. 既存アプリへログインする。UIDはserver側で確定し、表示名/LLM入力で選ばない。
2. 今回の構成では自分のAP account/personal projectを使える状態にする。必要なら招待を受ける。別AP画面を省くSSO/embeddingのUXは未検証。
3. AP標準Connectで自分のGoogle accountとscopeを確認し同意、Connectionを保存する。flowへの割当は我々/管理者が支援する。一般利用者へflow作成・GCP作成・secret貼付を必須負担にする設計ではない。
4. アプリの接続操作から自分のAP projectをAuthorizeする。Google同意とは別。今回はpublic PKCE client、state/S256/callback、subject/project/client/grantを照合。
5. 接続結果を確認して使う。失効/権限変更/期限切れなら本人が再認可し、企業policy拒否なら管理者へ確認する。
6. 終了時はapp接続解除とGoogle/Slack app access解除を区別する。token/code/cookie/secret/HARをチャットへ渡さない。

本人Google/AP同意は本人が行う。管理者のtemplate配布は無断の代理認可ではない。今回の実Googleは1利用者のテストfolderのみ。Slackのbot/user方式、複数の実Google利用者は未検証。

## アプリを提供する我々

| 実装・運用 | 確認した範囲 | 本番へ残る作業 |
|---|---|---|
| UID伝搬 | checked session → 署名/TTL/nonce付きjob → worker。UID別ADK namespace | 実認証へ適用、実履歴移行、全UI/API認可 |
| 本人binding | UID/AP subject/project/client/grant/generation。B実Driveを実行 | account/project登録、再binding、tenant/共有project運用 |
| AP client/接続UI | public PKCE/callback、本人Authorize、限定refresh/revoke、fail closed | production redirect/TLS、SSO方針、reconnect/障害UX |
| broker/vault | local DPAPI/owner ACL、世代失効、token除去、終了確認 | secret manager/rotate、跨host vault/lease、backup/事故対応 |
| 通常tool | lab_drive_search一つ、固定flow/folder/引数、世代。元台帳2/2 | 配布/版照合、追加toolの権限/出力/費用policy |
| 開発・管理 | 独立OAuthで公式42tools、元flowだけ読取/有効化 | operator権限・監査・短期認可。通常LLMへ管理toolsを出さない |
| Google方式 | AP標準中継で実2件。顧客独自GCPを必須にしない | 中継の条件/通信/保管。独自appなら担当/審査/secret管理 |
| LLM/ADK | 実Runner/tool execution、modelはscripted | 実LLM認証/費用/egress、自然言語判断、誤選択/prompt injection、表示 |
| 我々がAP運用 | 今回は専用local lab | AP基盤/TLS、key、backup、更新、監査、tenant、障害も我々が主担当 |

Google credentialをAPへ置いてもapp → AP tokenとUID対応は不要にならない。scope=mcpは検索専用権限でなく、CEにも編集/有効化等の管理toolsがある。brokerのdefault-denyを保ち、共通admin Bearerの利用者間流用や管理者JWT抽出を代替にしない。SSO/embedding/service API key等のedition・契約条件は別確認。

## 本番のGoogle方式

| 方式 | 管理主体 | 今回の確認 |
|---|---|---|
| AP標準中継 | AP側Google app。顧客/利用者の独自client作成を省ける | このCE配置でCLOUD_OAUTH2と実2件成功。全配置/将来版/企業policyの保証なし |
| 我々の独自app | 我々がGCP/client/branding/scope/必要審査/secret/rotationを担当 | 未採用・未検証。利用者一人ずつapp作成する意味ではない |
| 顧客専用app | 顧客管理者か合意した運用主体 | 未検証。企業の分離・policyに応じて選ぶ |

標準driveは全Driveを閲覧・管理できるrestricted scope。固定folderはGoogle grant境界ではない。狭いscope/Pickerと独自appの本番審査は別課題。[Google公式scope](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)

## 終了の担当

我々のbrokerがapp binding停止、AP revoke、local token除去、process停止を担い、HTTP200だけで失効宣言しない。最終snapshotは対象client/利用者active0・revoked5、元network/cache復旧を示した。historyは非公開で保持。

AP運用主体はConnection・run/log/backupの保管/論理削除方針を実行する。実ユーザーはGoogle/Slack app accessを解除し、管理者は退職/組織policyの失効を支援。今回Google ConnectionはACTIVEで残り、Google grant失効は未確認。AP Connection削除だけでGoogle revoke完了と扱わない。

AP flow-to-tool方式の検証であり、任意外部MCPを中継する汎用proxyは未実装。production全認可・複数実利用者・企業policy・分散/負荷・Google lifecycle・UI灰色表示は次の受入条件とする。
