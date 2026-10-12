# Drive 検索の次段階に必要な本人操作と承認

これは未実行の作業案です。今回は Google OAuth client/secret/grant、AP Connection、新 AP MCP grant、実ファイル、外向き通信、永続 credential を作成・変更していません。通常 Codex の public source/docs 取得許可から、AP 自体の outbound 許可は導きません。cloud OAuth 無効・outbound 封鎖の指示を維持し、停止済み内部 HTTP 試験は再開・別経路化しません。

## 認可方式を先に確定する

`AP_CLOUD_AUTH_ENABLED=false` のまま、[CE own-client OAUTH2 service](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/server/api/src/app/app-connection/app-connection-service/oauth2/services/credentials-oauth2-service.ts) と Connection UI の Client ID/Secret 入力を使う候補です。本人が管理する Google Web application OAuth client と Drive API の有効化が必要です。Platform 全体の OAuth app override は [固定 docs では Enterprise feature](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/docs/admin-guide/guides/manage-oauth2.mdx) で、CE の Connection ごとの own-client 方式と混同しません。service account key、domain-wide delegation、共有 admin token、cloud OAuth への切替は今回の案に含めません。

選択肢は「stock `drive` の広い権限を本人が明示的に認める」か、「検索用 auth/piece を狭い scope でレビュー・導入してから認可する」です。メタデータ用途には `drive.metadata.readonly` が候補ですが、Drive 全体の metadata を許す restricted scope です。`drive.file` を選ぶなら、既存 file の Picker/共有導線と見える corpus を先に実装・検証します。いずれもフォルダ q 条件を認可境界と表示しません。

本人の対象 Google account、専用 Cloud project/client、scope/audience/Testing status、対応する login UID/AP本人 project、Connection、検索 folder を、私的な記録で具体的に確定します。既存アプリと cleanup が干渉しない専用の test Cloud project/account を選べるか確認します。これらはまだ未選択です。secret、auth code、refresh/access token、browser cookie は chat に貼りません。

## Google Workspace 管理 policy

Workspace account の場合、管理者に対象 client ID と scope を示し、API controls の app access、対象 OU/group、Drive 制限、unconfigured app policy を確認します。Trusted は広く許可、Limited は unrestricted service のみ、Specific Google data は指定 scope、Blocked は拒否という区別です。本人 consent が組織 policy を上書きするとは扱いません。個人 Google account に組織管理者承認を一律要求しません。[公式 API controls](https://support.google.com/a/answer/7281227?hl=en)

外部 audience の Testing 状態で Drive scope を使う場合、refresh token は7日で期限切れになる仕様です。永続 refresh の試験と本番寿命を混同しません。公開 application の審査/assessment と、内部または test 運用に適用される例外の条件は別途公式要件・組織 policy で確認します。審査や費用発生を今回承認済みとはしません。[Google OAuth 仕様](https://developers.google.com/identity/protocols/oauth2)

## 通信先と現在の境界

| 実行主体 | 必要となる候補の宛先・用途 |
|---|---|
| 本人 Chrome | `console.cloud.google.com`：OAuth/Drive API の本人設定、`accounts.google.com`：login/consent、AP UI が表示する正確な localhost redirect URI、`myaccount.google.com`：終了時の app access 削除 |
| AP API / token refresh 処理 | HTTPS443 `oauth2.googleapis.com/token`：code exchange/refresh |
| AP worker の Drive action | HTTPS443 `www.googleapis.com/drive/v3/files`：`files.list` metadata。実 package が別 Google API hostname を使用する場合は、開始前に固定 SDK/source から宛先を追加レビュー |
| Google grant の programmatic revoke を選ぶ場合 | HTTPS443 `oauth2.googleapis.com/revoke`。本人 Account Settings で終了する案では AP のこの通信を前提にしない |

Browser が必要とする Google static asset/認証 redirect の詳細は未検証です。表は AP に広い `*.google.com` egress を与える理由ではありません。cloud OAuth 用 `secrets.activepieces.com`、download/export、upload、LLM/provider API はこの flow の宛先候補に含めません。新 piece の package 取得が必要なら、runtime Google 通信とは別に取得元・hash・保存先を承認します。

現在の AP は `AP_CLOUD_AUTH_ENABLED=false`、`AP_PIECES_SYNC_MODE=NONE`、`AP_NETWORK_MODE=STRICT`、`SANDBOX_CODE_ONLY`、internal Docker network のままです。STRICT 単独を public Google 通信の遮断証明として扱いません。AP/worker の実 Google 通信は未試験です。将来必要な許可は専用 AP API/worker の上記外向き通信について、対象 resource・期間・停止手順を示して本人承認を受けるものです。Docker Desktop 全体設定、OS security、H の Docker disk、既存 ingress/loopback container、他 project を変更しません。今回ネットワーク変更案を実装していません。

## 最短の本人操作案

1. 上記対象と scope、専用合成データ、権限/保管/cleanup、必要な専用 egress、AP piece 導入/import/publish と新アプリ runtime の範囲を親が本人へ提示し、対象別に承認を取る。
2. 本人が Google Console で承認済み client を作成または選び、Drive API、audience/test users と正確な redirect を設定する。AP の Connection UI が表示する URI をそのまま登録する。固定 source の redirect path は `/redirect`。現在 frontend URL からの候補は `http://localhost:18088/redirect` だが、表示値を確認せず採用しない。localhost 開発 URI の例外は [Google redirect 仕様](https://developers.google.com/identity/protocols/oauth2/web-server) にある。
3. 本人が Chrome で対応する AP本人 project を開き、Google Drive Connection の own-client 入力へ Client ID/Secret を直接入力する。本人だけが Connect/Authorize を押し、対象 Google account と画面 scope を確認する。popup/redirect の失敗は原因未分類のまま記録し、cookie 抽出・共有 Bearer・別 UI 経路で回避しない。CUA の既知エラーは解決したことにしない。
4. 承認済みの専用 folder に、合成名 `CMDBOX_LAB_ONLY_A.txt`、別名の除外用 file、必要なら合成 subfolder を本人が用意する。既存の無関係な file は使わない。今回 cloud 上には何も作成していない。最初は少数・My Drive・直下だけで行う。content の download は不要。
5. operator が owner project/Connection の一致を確認し、reviewed template の DUMMY reference を私的な manifest で置換、draft import、step property/Connection/valid status を確認する。本人の対象承認の範囲で publish/enable する。実 raw MCP name は discovery から取得して固定する。
6. 前回 A/B grant は終了済みなので、新たなアプリ↔AP 本人認可と purpose-bound runtime が必要。旧 token/settings を再利用しない。検索 alias の production schema/bootstrap/live manifest をレビューしてから、本人 UI consent を経て一つの UID で試験する。Google credential は AP の外へ出さない。

stock Google auth に `pkce` 宣言はなく、AP helper は宣言時のみ challenge を生成します。AP Google popup helper は code message の origin を検査します。この観察を Google Connection の state/PKCE/session-binding 全体の実証明とは扱いません。前段のアプリ↔AP OAuth 契約成功を Google 側の OAuth lifecycle 成功へ転用しません。

## flow 配布・更新の自動化調査

固定 [flow controller](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/server/api/src/app/flows/flow/flow.controller.ts) は新 flow の POST、flow ID 宛の `IMPORT_FLOW`、`LOCK_AND_PUBLISH`、`CHANGE_STATUS` という操作を扱います。CE の本人 USER session と project permission を使う手順が候補です。過去の合成 flow 配布成功から Google flow 配布まで検証済みとはしません。MCP broker 経由の管理 API、CE service key/SSO/Enterprise Git sync を前提にしません。

初回は承認された新 flow だけを作成し、local template digest と owner project / flow ID / published version / Connection reference の私的な対応表を残します。再実行はその記録を照合し、同一なら no-op、変更時は現在版と draft を比較してレビュー後 publish します。名前だけで既存 flow を上書きせず、記録不明・project mismatch・競合なら停止します。rollback は保存した前版を draft として確認し、別途承認範囲で publish。client、Connection、grant を flow import のついでに作成しません。この orchestration の実 API 自動化は今回未実装です。

## 終了の順序と証拠

1. 新 search tool の app binding を無効化し、新規呼び出しを止める。新しく承認された専用 app↔AP grant を通常 revoke し、本人 AP UI の対象 grant 状態を確認する。前回 audit は保持する。
2. 新検索 flow を disable。Google 側の専用 app access を本人 Account Settings で revoke/remove する。Google revoke は Cloud project 配下の他 client/scope にも影響し得るので、既存 app と共用 project なら事前に影響範囲を確認する。[Google 終了仕様](https://developers.google.com/identity/protocols/oauth2/web-server)
3. 今回専用の AP Google Connection を外し、client secret/保存 token の保管場所と削除を確認する。AP Connection の削除だけを Google grant の失効証明にしない。AP grant の失効だけを Google grant の失効証明にも使わない。
4. 承認した dedicated runtime の process/listener/cache/vault token を ownership 確認して終了。専用 Google client/secret と合成 file/folder の削除は具体対象と復旧不能性を示して承認範囲で行う。既存 AP client、owner bootstrap、volume、旧 audit、他 Connection を触らない。
5. sanitized result には scoped search、拒否、refresh、二種類の grant の終了確認と未検証を記録する。raw Google IDs/metadata/credential/browser session と AP run log は ignored private/data に分離し、保管/削除方針を確認する。削除を AP platform 全体の不在や SSD forensic erase の証明にはしない。

現在の blocker は、実対象選択、scope/piece 方式、専用 egress と credential 保管、本人 Google consent、新 app↔AP consent、live alias 登録の具体承認が未実施であることです。今回の許可済みローカル準備では自動承認拒否はありませんでした。
