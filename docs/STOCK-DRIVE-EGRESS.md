# 専用Google TLS中継・rollback案（設定のみ、未適用）

stock Drive/標準own-client OAuthを改造せず、必要なGoogle HTTPSだけを専用中継へ通す案。HTTP_PROXYで一括解決したとしない。own-clientのclaim/refreshは固定 `safeHttp.retryingAxios`、stock Driveは `@googleapis/drive20.2.0 → googleapis-common8.0.2 → gaxios7.1.3` と `google-auth-library10.5.0`。両経路の異なるproxy挙動を推測してcredentialを平文forward proxyへ渡さない。

[review manifest](../templates/stock-drive-egress-review.json) はenabled=false。新bridge/host mapping/SSRF例外と実relayを適用していない。固定official imageを依存として取得し、networkなしの一時containerでnginx1.30.5のstream/ssl_preread moduleを確認した。元templateの `nginx -t` は本配置IP未割当によるbind error99で終了。listenだけを `127.0.0.1:10443` に置換した専用copyでは構文確認が成功した。一時containerは除去済み。実配備bind/TLS route、AP sandboxの名前解決継承、通常Google API経路の疎通は未試験。停止済み内部HTTPの境界試験はこの案の検証項目に含めず、復元・別network/URL/process化しない。

## 正確な候補値

| resource | 候補値と境界 |
|---|---|
| AP対象 | 今回の既存専用AP API/worker containerだけ。exact name/元compose/env/networkは所有者private planで固定する。旧ingress、停止済みloopback、他containerを転用しない |
| 新内部bridge | `cmdbox-stock-drive-relay-internal`、internal=true、候補subnet `172.30.92.0/28`。既存net/host/VPNとの衝突があれば適用せず別値を再レビュー |
| 内部address | relay `172.30.92.2`、承認対象AP `172.30.92.3`。APが増える場合はsource allowlistを勝手に広げない |
| 新外向bridge | `cmdbox-stock-drive-relay-egress`、新relayだけを接続。AP自身は接続せず、既存内部networkを維持する |
| 新relay | `cmdbox-stock-drive-relay`。host published portなし、volumeなし、config read-only、root fs read-only、tmpfs `/tmp`、restartなし、試験最大2時間。Docker data配置は既存のまま |
| image | official `docker.io/library/nginx:stable@sha256:6e2a172ae5503c0df64cd3294b57c86394ced402016a8cc45436086fa51f5d02`（linux/amd64 image digest、取得時tag metadataで確認）。依存image取得とmodule/構文確認は上記offline範囲で実施。実配備・security受入確認は未実行。更新するなら別digestをレビュー |
| AP hostname mapping | このAP containerだけ `oauth2.googleapis.com` と `www.googleapis.com` をrelay IPv4に解決。host/Windows/ChromeのDNSやhostsを変えない |
| AP SSRF例外 | `AP_NETWORK_MODE=STRICT` のまま、現在の `AP_SSRF_ALLOW_LIST` に単一relay IPだけを追加する候補。元値を保存し、広いCIDR/loopback例外やguard無効化を行わない。これは承認が必要な専用AP security設定変更 |
| Google upstream | exact SNI `oauth2.googleapis.com:443` / `www.googleapis.com:443` のみ。unknown/empty SNIはupstream空で失敗。任意host/IP/portを入力しない |
| SDK/credential | HTTP_PROXY等を追加せず、stock/client/sourceは変更しない。AP→Google TLSを終端しない。CA追加・証明書検証無効化・secret inspectionなし |

[nginx候補config](../templates/stock-drive-relay.nginx.conf) はstream ssl_prereadでSNIだけを選び、暗号化されたTLSをGoogleへ転送する。sourceはAPの専用内部address一つに限定する。exact upstream hostをrelay自身の通常DNSで解決し、APのhostname mappingをrelayへ適用しない。relay access logなし、errorはcritのみ。TLS終端用certificate/keyは不要。[Nginx stream proxy](https://nginx.org/en/docs/stream/ngx_stream_proxy_module.html)、[ssl_preread](https://nginx.org/en/docs/stream/ngx_stream_ssl_preread_module.html)、[stream access](https://nginx.org/en/docs/stream/ngx_stream_access_module.html)

この中継はhostname/port境界であり、暗号化されたURL path・HTTP method・API件数を検査しない。同じGoogle host内の他APIをnetworkで拒否する保証はない。metadata検索への限定はreviewed flow、UID/project manifest、AP本人認可とアプリallowlistが担う。Google API DNS IPは固定せず、Google endpointのTLS certificate検証はAPの標準clientに残す。

## 本人承認後の実施前条件

1. exact対象AP containerと所有compose/env、全network attachment、hostname mapping、`AP_SSRF_ALLOW_LIST`元値をignored private snapshotへ保存。元AP encryption/signingキー、owner/client、volumeを更新・再初期化しない。
2. subnet/名前/port/module/config/imageの衝突を確認する。official pin imageでnetworkなしの `nginx -V`/`nginx -t` を確認する。stream/ssl_preread moduleがなくconfigが拒否されたら停止。取得だけでruntime成功とは扱わない。
3. 具体network/hosts/単一SSRF例外/専用AP再起動の承認を確認してから、新relayと二つのowned bridgeを作り、対象APだけを内部bridgeに追加する。APを外向bridgeへ接続しない。既存compose/接続を保存した値で差分レビューする。
4. この通常Googleアプリ経路だけを対象に、Google consent前の設定照合、本人のown-client Connection UI、承認された少数metadata検索を確認する。未分類失敗を遮断成功と扱わず、SSRF例外追加・host増加・別URL試験で回避しない。
5. 2時間の専用終了担当を本人/親で確定する。local app deadlineはrelayやAP Google Connectionの停止を自動実行しない。app停止とremote cleanup/egress rollbackの別証拠を残す。

現在のinternal Docker network/STRICTだけでGoogle封鎖が証明済みとはしない。[Docker internal network仕様](https://docs.docker.com/reference/cli/docker/network/create/) は構成説明であり、このAPの実通信試験ではない。global Docker設定、OS firewall、Windows hosts、H側Docker diskは対象外。

## rollback

新app bindingと新flowを停止し、新AP/Google grantの本人終了確認を先に行う。対象APのhosts/SSRF値とnetwork attachmentを保存済みの元値へ戻し、その専用APだけを元composeから再起動する。新relayを停止し、今回作ったbridgeはattachmentがなく今回所有が確認できた場合だけ除去する。旧network/volume/client/owner bootstrap/auditを削除しない。snapshotと新rootは戻し用に保持し、異常時に既存workspaceを上書きしない。

この資料は実施可能性をレビューする候補であり、offline構文確認を実egress成功へ転用しない。実TLS relay・AP解決継承・remote cleanupは未検証。実適用直前の構成/イメージ確認と具体resource承認が未完了の間、Google/AP consentを始めない。
