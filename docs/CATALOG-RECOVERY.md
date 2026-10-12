# 公式カタログ復旧完了と適用範囲

状態: 公式候補13,475件まで標準同期完了。APと指定namespace helperは稼働・healthy、同期NONE・元env/hosts/networkへ復帰済み。一時relayとbridge二件を撤去した。長時間の復旧コマンドは残っていない。

## 原因と結果

固定AP CE0.92.2の既存compose/実設定がAP_PIECES_SYNC_MODE=NONEで、公式取得前に同期を終了していた。初期の公開catalog/registryは0件、DBにはplatform-scoped CUSTOM/ARCHIVEのHTTP0.12.1/MCP0.0.21だけがあった。既存実行cacheとUI用公式catalogは別管理である。

最初の安全な引継ぎで13,361版まで保持し、再開では残り114版を追加、削除0・取得失敗0。起動時と毎時ジョブが重なり、二つの完了記録の追加は63+51=114だった。完了後DBは13,475版、公開公式registryは13,473版、公開一覧770種類。差の二件は保全した旧scoped登録であり、未完了候補ではない。

Drive0.11.0はOFFICIAL/REGISTRYで正式GET可能、最新表示は0.11.3。A/Bのproject指定公開GETは双方でDriveを返した。このGETのprincipalはUNKNOWNで、本人sessionでの認証付き表示を実証したものではない。

## own-clientとMCP競合の切り分け

Drive authはOAuth2とCUSTOM_AUTHの配列で、固定UIは配列を扱う。OAuth2のscope候補はdrive/email。cloud-auth=false、platform OAuth overrideはDBで0件、Google用redirectはhttp://localhost:18088/redirect。通常accountにはOAuth2 own-clientを選び、driveだけの選択を本人画面で確認する。CUSTOM_AUTH/service accountは選択しない。Google grant、credential入力、Connect/Saveは今回行っていない。

MCP0.0.21の匿名global GETは404、公開最新は0.0.20だが、既存0.0.21は削除せずscoped CUSTOM/ARCHIVEとして保持した。固定同期はname/versionだけで既存判定するためglobal版の追加をskipする。

隔離DBでA/B両方のsubject/projectとMCP旧登録のplatform一致を確認した。固定sourceのfilterPieceBasedOnTypeは、OFFICIAL/globalまたは要求platformと一致するCUSTOMを許可する。このためglobal404だけで両利用者のmetadata解決不可とは判断しない。Drive接続UIはGoogle Drive metadataを用い、MCP登録のglobal分類はその接続作成の前提ではない。既存flow二件はMCP0.0.21を参照し、定義・archive sourceを含むfile・必要版・scope関係を保全した。新grantなしで実flow再実行やDrive実行は行っていない。productionでの包装分類統一は別の運用判断で、今回の復旧に旧登録の削除/上書きを追加していない。

## 検証と回復可能性

前回と今回を分け、G内ignored privateにCurrentUser+SYSTEM限定ACLでcompose/env/container構成と整合data snapshotを保持。今回前後は約544MB/546MB。masterを変更せずコピーを同じPGLite0.3.14/vectorで開き、networkなしで81テーブルを読取り、master hash不変を確認した。

81テーブル中79の内容hash一致。既存flow/flow版各二件、Connectionゼロ、user/project/platform/MCP client/token/OAuth app/署名key/API key/file等は不変。project_role差分はupdated日時だけで、ID・permission集合・その他内容は一致する。既存public-clientの存在、none認証、既存callback一致、client secretなしも確認した。owner bootstrap、元volume、秘密keyを維持し、新client/grantは作成していない。

## 通信と復帰

許可されたcloud.activepieces.com:443だけを、AP専用source addressとSNIを固定した一時TLS pass-through relayへ通した。取得済み固定official nginx imageを用い、公開port/CA変更/TLS終端/HTTP_PROXYなし。APは内部networkだけ、外向bridgeはrelayだけ。telemetry/tool-searchは元からfalse。

対象APと指定helperを元設定へ復帰し、env全key/value・extra_hosts・network attachment・helperの元image/command/mountと新AP参照を読み戻した。一時relay/bridge二件を所有確認後に除去。同じ許可済みcatalog HTTPS URLへの5秒上限通常fetchはEAI_AGAINでHTTP未到達。この一件を全network境界の成功証明とはしない。停止済み内部HTTP境界probeの復元・再試験・転用、他host許可、OS/global Docker変更、Chrome操作は行っていない。

## 残る確認

既存owner-session.jsonのJWTを抽出してlocal read-only APIへ再利用する案は、自動承認レビューが「既存セッション秘密の使用に明示承認がない」として拒否した。該当要求は未実行で、別経路のsecret使用で回避していない。公開GETと非secret scope関係による確認を、認証付きA/B表示の成功と置き換えない。直接確認には本人ブラウザでの確認、または当該sessionの用途限定使用に対する明示承認が必要。

Google/AP本人認可、専用Connection/flow、実行package依存取得、Google用egress、実stock実行/remote cleanupは今回のcatalog復旧から承認済みとは扱わない。テストデータIDは未受信扱い。次の本人確認はAP再読込み→Google Drive→OAuth2のown-client欄/redirect/drive-email選択で、Connect/Save/secret入力はまだ不要。

数値は [summary](catalog-recovery-summary.json)。実識別子・env・生log・大規模metadata・backupはGit対象外。commit/push/PRなし。
