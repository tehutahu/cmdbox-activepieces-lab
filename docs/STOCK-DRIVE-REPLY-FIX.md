# Reply式・Publish・管理MCPの障害整理

[最終E2E](GOOGLE-DRIVE-E2E.md)では初回返却契約失敗を修正し、最後の1回で2件取得。元台帳2/2、AP grant失効、app/worker停止、元通信/cache復旧が完了。Google Connection/Google grantは別扱い。

## Replyの型とwrapper

schema27の `{{step_1}}` はstep stateで配列ではない。正しくは `{{step_1['output']}}`。初回drive_result_limit_exceededはobject型拒否で、20行超過の観測ではない。

AdvancedのResponseはJSON editorで本文contract/policyId/completion/filesだけを入れる。APIはdynamic propertyによりinput.response.responseへ保存、SDKは既知wrapper一つを解く。UIへ外側responseを足すと二重包装になる。[固定piece](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/pieces/community/mcp/src/lib/actions/reply-to-mcp-client.ts)

## Publishの読み戻し

UIはfetch failedを表示したが、修正版はpublished LOCKED/valid、flowはDISABLED、draftなし。ログでtrigger有効化失敗を確認したが送信先・根本原因は未確定。

公開cacheをオフライン復元し、開発MCPで同flowを読取、ap_change_flow_status(ENABLED)が成功。再編集・再Publish・同名flow作成/削除はしていない。元cache復旧後もENABLEDを確認。Google stepの灰色/空panelは未解決で、実Google action成功とは別。

## 公式管理MCP

CE0.92.2のap_*管理tools42個を実測。独立開発OAuthでap_flow_structure/ap_read_step_settings/ap_change_flow_statusを使用。必要な編集/Publishにはap_update_step/ap_lock_and_publishもある。[固定登録](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/server/api/src/app/mcp/tools/index.ts)

通常cmdboxはlab_drive_searchのみ。管理者JWT抽出/再利用、DB直接書換え、新API key、通常runtimeへの管理tools公開はなし。開発grantも失効確認済み。新接続は対象/scope/期間/終了を再承認する。
