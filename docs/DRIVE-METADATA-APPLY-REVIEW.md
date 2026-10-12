# metadata 検索を実 AP/通常 Google account へ適用する前の review

本人は通常 account の Drive を選びました。これは account 選択の意思であり、新 client/secret/Connection/Google grant/AP grant、piece install、flow import/publish、egress、実データ送信の承認ではありません。以下の対象別確認を親へ返すための具体案です。今回はいずれも未実施です。旧 stock 準備と phase2 を保全し、停止済み内部 HTTP 境界試験を再開・別経路化しません。

## 最初に承認する対象

| 対象 | 提示・確定する範囲 |
|---|---|
| 通常 Google account | 本人が browser 内で選択・確認。具体 email/subject は私的記録のみ。connected app から推定しない |
| 検索 folder/data | 本人の通常 account の明示 My Drive folder、一つの固定 term、直下の name/id/mimeType、最大20行/5 request。最初は本人が合成名の少数 file を用意する案。作成/削除は別対象として確認 |
| Google OAuth | 既存 app と cleanup が干渉しない専用 Cloud project と Web application client、Drive API、metadata readonly scope、一つの新 AP Connection。別 Google account は要求しない |
| package | `@cmdbox-lab/piece-drive-metadata-search@0.1.0` archive と hash、AP CE `0.92.2` の platform-level custom install。Google token を含まないローカル bundle |
| flow | 対応する login UID/AP本人 subject/project 内に新検索 flow 一つ。draft import、確認後 publish/enable。既存 flow は上書きしない |
| app↔AP | 新本人 grant/runtime と search alias の production 接続。前回 A/B grant/token は終了済みで再利用しない。shared admin Bearer/新 secret API key は使わない |
| 通信・保管 | 下記専用 AP API/worker egress、終了時刻（提案は最長2時間）、Google/AP grant の別々の revoke、credential/cache/data cleanup 範囲、削除できない log/backup の扱い |

scope は **`https://www.googleapis.com/auth/drive.metadata.readonly`** です。許可される credential 自体は対象 folder 以外のアクセス可能 metadata も読めます。操作を folder で絞っても scope は縮まりません。取得 name/id/mimeType は Google→AP worker/run storage→cmdbox worker/ADK session→本人 Web UI に流れます。今回案では外部 LLM、内容取得、download/export/upload はありません。AP run/history と cmdbox session に実 metadata が保存される可能性も対象に含めて承認します。[Google scope 仕様](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)

## CE の導入経路と制約

固定 [community controller](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/server/api/src/app/pieces/community-piece-module.ts) は `POST /v1/pieces` を platform-admin `USER` または `SERVICE` に提供し、[install service](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/server/api/src/app/pieces/piece-install-service.ts) は `ARCHIVE` を保存して worker metadata extraction を実行します。今回選ぶ将来の actor は本人の既存 USER login です。新 API key を作る CLI publish は使いません。

multipart の対象は `pieceArchive`（review済 tgz）、`pieceName`（上記独立名）、`pieceVersion=0.1.0`、`packageType=ARCHIVE`、`scope=PLATFORM`。通常 AP API base の `/v1/pieces` に送る案です。現在 frontend localhost18088 なら候補は `/api/v1/pieces` ですが、実 base/route は通常の public API/UI と固定 source で確認してから採用します。archive は package.json、src/index.js、THIRD-PARTY-NOTICES.txt の3 entry に限定し、secret/credential/source tree/node_modules を含めません。

ただし、固定 [Install Piece UI](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/web/src/features/pieces/components/install-piece-dialog.tsx) は Archive を plan の `managePiecesEnabled` と `PRIVATE_PIECES_ENABLED` で gate します。固定 [flag default](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/server/api/src/app/flags/flag.service.ts) は COMMUNITY で private pieces を false にします。**CE UI で Archive を押せると断定しません。** 本人 admin による community API route の直接 install を、対象 hash/範囲/公式 route とともに別途承認する案です。runtime の capability/auth/license 条件で拒否されたら blocker を返し、flag 改変・Enterprise 偽装・別 endpoint で回避しません。今回は AP route/DB へ何も送っていません。

承認後も、最初に uploaded package identity/version/scope、installed metadata、sandbox での dummy action、Connection の piece/project、flow の published snapshot、operator 固定 input、empty MCP schema を確認します。既存同名/version があれば置換せず hash と現在版を照合し、必要なら独立新 version として再レビュー。archive install は platform scope に残るので、終了時に残すか取り除くかも明示します。既存 AP owner/client/bootstrap/volume は触りません。

## 正確な redirect と本人 OAuth 操作

1. 本人 Chrome で対象 AP本人 project の Connection 作成を開き、**独立 metadata piece**を選ぶ。cloud OAuth を無効のまま own-client `OAUTH2` の Client ID/Secret 入力方式を選び、Connect を押す前に表示された **Redirect URL 全文**を取得する。
2. 固定 [Connection UI](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/web/src/app/connections/oauth2-connection-settings.tsx) は platform の third-party redirect flag からこの表示値を作ります。cloud auth の `secrets.activepieces.com/redirect` は採用しません。現 frontend の候補 `http://localhost:18088/redirect` を表示未確認のまま登録しない。missing/異なる host/path/scheme は止めて原因を確認する。
3. 本人が Google Console にて承認済み専用 Cloud project/Web OAuth client を作成・設定し、取得した URI を authorized redirect URI に完全一致で登録する。localhost URI の例外は [Google Web OAuth 仕様](https://developers.google.com/identity/protocols/oauth2/web-server) で確認する。Drive API と audience/test user は通常 account に合わせる。Workspace 管理下なら API controls 制約も本人/管理者が確認する。
4. Client ID/Secret は本人が AP Connection UI に直接入力する。chat/public Git に貼らない。表示 scope が metadata readonly **一つ**、対象 account、AP project/Connection が承認対象と一致することを確認し、本人だけが Connect/Authorize/consent を行う。
5. 保存後、実 token response の top-level scope を私的な検査で確認し、一致しなければ検索を停止する。新 Google grant/Connection は旧 grant の lifecycle 成功証拠を継承しない。PKCE はこの Web own-client piece に未宣言で、Google Web PKCE 対応を推定して有効化していない。state/origin/session-binding と Google refresh/revoke の実確認は別試験。

scope の意味と送信先を本人に示してから実 grant を作る。ブラウザ cookie 抽出、secret を公開 query/input に入れる方法、共有 admin token へ置換して consent を回避する方法は含めません。CUA の既知エラーは修復済みとは扱わず、本人の通常 browser 操作と非秘密の確認結果を使う案です。

## 専用 egress の具体案（未設定）

| 実行主体 | 許可候補 |
|---|---|
| 本人 browser | `console.cloud.google.com` 設定、`accounts.google.com` login/consent、AP 表示の localhost redirect、`myaccount.google.com` 終了確認。Google browser asset/redirect の追加先は実確認が必要 |
| 専用 AP API/token refresh | TCP443 `oauth2.googleapis.com`、path `/token` の code exchange/refresh。本人操作でのみ使用 |
| 専用 AP worker action | TCP443 `www.googleapis.com`、GET `/drive/v3/files` と固定 query/fields。alt=media、export、upload、他 path を許可しない |
| Google programmatic revoke を別途選ぶ場合 | `oauth2.googleapis.com/revoke`。本人 Account Settings 操作案では server からのこの通信は不要 |

具体対象候補は既存専用 AP `ap-cmdbox-task3-activepieces-1`（同居する API/worker）、新規 owned proxy `ap-cmdbox-task3-drive-egress`、新規専用 egress bridge 一つです。proxy は既存 `ap-cmdbox-task3_ap_task3_internal` と新 bridge に接続し、AP 本体を直接外向き bridge へ接続する案にはしません。既存 ingress/worker-loopback は転用しません。AP API/worker の標準 proxy 対応設定が使えるかは source/runtime で別途確認が必要で、適用に専用 AP の再起動/再作成が必要ならその稼働影響も承認対象です。

専用 compose/runtime だけを対象に、review 済 local image/archive を使う **追加の明示 egress proxy** と必要最小の network attachment を設ける案です。元 compose/config/network attachment を私的に保存し、試験の終了時刻にこの lab の追加分だけ停止・detach・元構成へ戻す reversible rollback を準備します。shared Docker daemon、OS firewall/security、H の Docker disk、unrelated container/volume は変更しません。今回 proxy/network は作成していません。

TLS CONNECT の hostname allowlist だけでは HTTPS path/method を制限できません。path は piece の固定 URL/GET で制限し、proxy が hostname までしか検査できない場合はその限界を明示して承認を取ります。certificate interception や global CA/security 変更は提案に含めません。AP STRICT/SANDBOX 側の proxy compatibility・宛先許可も未検証で、拒否を internal-HTTP/別 URL/別 process の probe で回避しません。

許可期間は承認した試験枠のみ。`*.google.com` 全体、cloud OAuth secrets host、LLM/provider host、package registry は runtime Google 通信に混ぜません。dependencies/archive は事前に通常 Codex source/registry access で G に取得済みのものを使い、AP の外向き package 取得が実際に必要なら別途対象を提示します。現在の `AP_CLOUD_AUTH_ENABLED=false`、pieces sync NONE、STRICT、SANDBOX_CODE_ONLY、internal Docker network を今回は維持しています。

## 保管、終了、再現記録

提案は開始から最長2時間で新 app binding を無効化し、新 search flow を disable、新 app↔AP grant と Google app access を **別々に**通常 revoke することです。自動2時間 teardown はこの Drive path へ未接続なので、実施前に終了担当・時刻・手動 fallback を決めます。Google External Testing の refresh token7日失効を保管上限/削除保証と扱いません。[Google OAuth](https://developers.google.com/identity/protocols/oauth2)

Google client secret/refresh token は AP Connection storage、app AP token は purpose-bound private vault に保存する案です。公開側は alias/schema/template/hash と sanitized result のみ。AP run/history、cmdbox session、backup の metadata/credential retention を開始前に特定し、専用 record の削除可否と残存範囲を記録します。platform 全体や volume の削除で代用しません。

終了順は binding off→flow disable→新 AP grant の本人 UI 終了確認→Google Account Settings の専用 app access revoke→新 Connection の token/secret 削除確認→専用 app runtime/listener/cache/vault token cleanup→承認済追加 egress の rollback。Google revoke は同 Cloud project の他 client/scope に影響し得るため専用 OAuth project/client を推奨します。今回専用 client/合成 file/folder/archive の削除は、対象と不可逆性を示して別途承認済み範囲で行います。前回 audit、既存 AP clients/bootstrap/volumes、他 Connection を保持します。

run private manifest には UID/AP subject/project/flow published version/Connection/raw name/folder/policy/package hash と開始終了時刻を固定します。同じ記録の再実行は照合して no-op、競合・identity mismatch・記録不明は停止。name のみで既存 flow を上書きしません。更新は保存した前版と差分をレビューし、別途承認後 publish。distribution 自動化と実 Google lifecycle は今回未実装です。

現在の残条件は、具体 account/folder、platform archive install と CE runtime 可否、own-client/Connection/二種類の新 grant、専用 egress/保管/終了の承認、production alias wiring、実 sandbox/Google lifecycle の確認です。通常 account 選択以外の実適用は行っていません。ローカル準備で新しい automatic approval rejection はありませんでした。
