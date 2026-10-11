# 次の課題と完成条件

更新: 下記の初期local/mock項目は[継続検証](CONTINUATION.md)の限定範囲で実装・通過しました。設定の明示mode、fake lifecycle、2 Web/worker、合成ADK履歴移行、選択した標準resource/admin APIを対象とします。残る実AP/provider/production vault/全UI/API/実履歴の条件は同文書の未検証欄を参照してください。停止済み境界試験の再開は含みません。

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
