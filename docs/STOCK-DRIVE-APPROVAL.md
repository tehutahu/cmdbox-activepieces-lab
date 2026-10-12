# stock Driveの再認可・終了チェックシート

[2026-10-12実E2E](GOOGLE-DRIVE-E2E.md)は終了済み。元台帳2/2・残り0。この資料は次の操作の自動承認ではない。Google/AP同意、対象、通信先、期間、保管/終了を具体化して新承認を取る。

## 方式を先に選ぶ

| 方式 | 必要な準備 |
|---|---|
| AP標準中継（今回成功） | AP側Google app、本人consent、Connection owner/project、企業policy、scope、中継通信/保管。顧客/利用者の独自GCP作成を必須にしない |
| 我々の独自app | 我々がGCP/client/branding/redirect/scope/必要審査/secretを担当。未検証 |
| 顧客専用app | 顧客管理者または合意した運用主体が同じ設定を担当。未検証 |

旧own-client前提案は今回の成功経路に採用していない。Google → APのprovider redirectとapp → APのPKCE callbackを混同しない。secret/token/code/cookie/HARをチャット/Gitへ渡さない。[役割分担](RESPONSIBILITIES.md)

## 非公開の対象表

| 対象 | 所有者が固定するもの |
|---|---|
| app | stable UID、protected root、同じ検索台帳/消費数、期間、正常/失敗時終了 |
| AP | 本人subject/project、public PKCE client、scope=mcp、grant/交換/refresh予算、flow/published版/raw名/Connection所有者 |
| Google | 本人account、OAuth方式、scope、test folderと少数file。実IDはprivateのみ |
| flow | 固定folder/name/type、空引数、schema27 Reply式、最小metadata。公開DUMMYを実設定にしない |
| 通信 | 今回の3hosts HTTPSは終了。次回も必要先・期間・元env/network/cacheのrollbackを明示 |
| 保管 | AP Connection、run/log、app vault/history、browserを別扱い。永久削除を推定しない |

scope=mcpは管理toolsも含む。開発用の正規MCPは独立目的/短期認可/同flowに固定し、通常 `lab_drive_search` allowlistを広げない。管理者JWT抽出、DB直接書換え、無承認のcreate/delete/Testをしない。

## 本人操作と受入

1. 標準Connectで本人account/scopeを確認してConnectionを保存。今回はdriveのみ・emailなし。企業policy/追加scopeは再確認。
2. 同flow/Connection/published版/式を照合。既に修正LOCKED/valid・DISABLEDなら再Import/Publishを繰返さず、正規ap_change_flow_statusを検討。
3. 終了監視を認可/通信より先に設定。本人だけが同projectをAuthorizeし、state/S256/subject/project/client/generationを照合。
4. 同じ元台帳の残りを確認し承認回数だけnative経路で実行。成功/最後の失敗で早期終了。外部LLMは別の認証/費用/egress/受入条件。

## 終了の受入

| 場所 | 確認 |
|---|---|
| app/local | binding停止、通常revoke、token/pending/lease除去、Web/callback/worker停止。historyは今回非公開read-only保持 |
| AP grant | HTTP200は提出確認。対象active不存在/revokedを別確認。今回active0・revoked5 |
| AP Google Connection | 今回CLOUD_OAUTH2/ACTIVEで保持。削除は別承認、AP記録除去を確認。Google revokeの証拠にしない |
| Google grant | 本人が該当app access解除。今回は未確認。標準共有appの同account他接続への影響も確認 |
| network/cache | relay/bridge撤去、元env/hosts/network/image/mount/cacheとhealthy。今回確認済み |
| log/backup/browser | 所有/保管/削除を合意。volume丸ごと削除、未承認history削除、browser/SSD全消去保証にしない |

完全provider cleanup、独自Google client、企業policy、production vaultは未検証。停止済み内部HTTP試験再開、global Docker/OS security変更、他project停止を承認項目へ混ぜない。
