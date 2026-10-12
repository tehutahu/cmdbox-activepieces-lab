# 次の課題と完成条件

2026-10-12の[標準Drive E2E](GOOGLE-DRIVE-E2E.md)で、native cmdbox→Redis→worker→実ADK scripted→AP標準flow→実metadata2件と終了を確認。AP標準中継が成功し、顧客独自GCPを通常利用の必須条件にしない。[役割分担](RESPONSIBILITIES.md)

## 完了した限定範囲

- [phase1](CONTINUATION.md)：static/UID mode・fail closed、fake lifecycle、2 Web/worker共有guard、合成UID移行、選択したresource/admin API認可。
- [phase2](PHASE2-VALIDATION.md)：A/B本人binding、合成flow、限定refresh/revoke、native経路、本人UI witness。
- 今回：標準Google Connection・実2件、修正式、管理MCP42tools/通常allowlist分離、元台帳2/2、AP grant失効・token除去・元通信/cache復旧。

## 次の受入条件

| 対象 | 残る作業 |
|---|---|
| 自然言語/実LLM | model/credential/費用/egress、意図から許可toolを選ぶ判断、誤選択/prompt injection、表示。今回はscripted |
| 一般利用者UX | stable UID、AP account/project、本人Google/AP同意、割当、reconnect。SSO/embedding条件 |
| 顧客policy | Workspace/Slack app/scope/組織制限。個人Google成功を企業許可にしない |
| Google方式 | 標準中継と提供側/顧客の独自appを選ぶ。独自GCP/branding/審査/keyは別検証 |
| 複数の実利用者 | 新OAuthの複数Web/跨host vault・lease、実AP並行refresh/revoke、tenant、負荷。mockと区別 |
| 本番基盤 | lab signin fixture/DPAPI/loopback HTTPをproduction認証/TLS/Redis ACL/vault/監査へ適用 |
| flow配布/更新 | template、Connection所有者、published版/raw名の継続照合、多数projectのidempotent配布 |
| Google結果 | 広いscope、取得paging量、trash/incompleteSearch、共有Drive、大量結果。folderはgrant境界でない |
| Google終了 | 残るACTIVE ConnectionとGoogle grantを対象別承認して確認。AP revokeとは別。完全削除未実施 |
| UI/Publish診断 | 灰色/空panel、enable fetch失敗の通信先・根本原因。cache復元後成功だけで断定しない |
| API/履歴 | 実履歴UID移行、全UI/動的API ACL。選択dummy handler成功は全体完成でない |
| 他provider/proxy | Slack user/bot境界と任意外部MCP proxyは未実装/未検証 |

## 次の実資源操作

元台帳2/2・残り0。対象account/project/client/flow/Connection/folder/scope、通信先、期間、終了/保管を明示し新承認を取る。失効grant・終了通信枠の再利用、別台帳/リセットによる今日の3回目をしない。通常公開再現はdummy-only。[承認チェックシート](STOCK-DRIVE-APPROVAL.md)

## 再開しない安全停止範囲

停止済み内部HTTP境界試験を再実行せず、別network/URL/process/sessionで回避/debugしない。未分類失敗を隔離成功にせず、再実行機能をrepoへ入れない。global Docker/OS security変更、他project停止、volume削除、公開tunnelを継続作業へ混ぜない。
