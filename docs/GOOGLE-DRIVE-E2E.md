# 標準Google Drive E2Eの結果（2026-10-12）

既存login UIDから、native cmdbox Web → shared Redis → native worker → 実Google ADK → UID broker → AP CE標準Drive flowを通じ、用意した2ファイルのmetadataを取得できた。成功経路はAP標準OAuth中継であり、顧客・実ユーザーの独自GCP OAuth clientをAPへ登録する必要はなかった。[役割分担](RESPONSIBILITIES.md)、[本番に残る条件](NEXT-STEPS.md)、[集約JSON](google-drive-e2e-summary.json)。

実ADKのmodelはscriptedで、決められた `lab_drive_search` を呼んだ。自然言語から意図を解釈しtoolや検索条件を自律選択するLLMの成功証明ではない。一般顧客への配布・本番運用も未完了である。

## 観測した結果

| 項目 | 実測と限界 |
|---|---|
| 固定構成 | 公開cmdbox0.8.5.4の独立patch copy、ADK2.8.0、AP CE0.92.2、Drive0.11.0、MCP0.0.21、schema27 |
| 本人認可 | 既存public PKCE client、本人の同project Authorize、callback/state/S256、AP userinfoとsubject/project/client/grantを照合 |
| Google接続 | 本人が標準ConnectでConnectionを保存。CLOUD_OAUTH2。driveを選びemailを外した限定経路 |
| 経路 | native password login、WebSocket、署名Redis job、worker検証、実ADK scripted、公式MCP SDK、AP標準Drive action |
| 結果 | CMDBOX_LAB_ONLY_A.txt / CMDBOX_LAB_ONLY_B.txt の2件。期待file ID一致も非公開historyで確認 |
| 対象 | 固定folder・name条件・type=file・空引数。通常runtimeはlab_drive_search一つ |
| 試行 | 同じ元SQLite台帳で2/2。初回は返却契約失敗、最後の1回が成功。新runでリセットせず残り0 |
| 終了 | app/callback/worker停止、local token除去、元env/network/cache復旧、relay・一時bridge撤去、AP healthy |
| AP grant | 最終整合snapshotで対象client/利用者のactive0・revoked5。HTTP200だけを失効証拠にしない |
| 保管 | history/session/event/stateは非公開で保持。Google ConnectionはACTIVEで残存、Google grant失効は未確認。永久削除なし |

指定した少数ファイルのmetadata取得であり、全Drive検索・書込み・共有Drive・trash除外・検索完全性・他の実Google利用者・負荷の検証へ一般化しない。stockは1ページ1000件でnextPageToken終端まで取得し、アプリの20行返却上限はGoogle取得量の上限にならない。[stock制限](STOCK-DRIVE-RUNTIME.md)

## 実測・見込み・未検証の一覧

| 区分 | 内容 | 根拠・限界 |
|---|---|---|
| 実測 | native cmdboxから標準Drive flowでmetadata2件 | 1利用者・固定folder・実ADK scripted。自然言語判断ではない |
| 実測 | AP標準OAuth中継と二段の本人認可 | 成功経路で顧客独自GCP client登録なし。企業policyへの一般化なし |
| 実測 | 公式管理MCP42toolsと通常1toolの分離 | 開発接続で元flow読取/enable。通常allowlistを拡大していない |
| 実測 | 初回Reply型失敗の修正、最後の1回成功 | 元台帳2/2。実3回目なし。根本通信先/灰色UIは未解決 |
| 実測 | AP grant失効・token除去・停止・元構成復旧 | active0。Google Connectionは残存、Google grant失効未確認 |
| 見込み | 既存UIDで利用者別flow/Connection基盤を組み込める | 公開patchとbroker契約が実装参考。実顧客アプリ移植完了ではない |
| 見込み | template配布と標準中継で利用者の準備を減らせる | 多数顧客配布、一般利用者UX、SSO/embeddingは未検証 |
| 未検証 | 自然言語LLM自律選択・本番認証/vault/TLS・多host/負荷 | 別の受入試験が必要 |
| 未検証 | 企業OAuth policy・複数実Google利用者・独自client・Slack | 個人Googleの限定成功で代替しない |
| 未検証 | 完全provider cleanup・UI原因・任意MCP proxy | Connection/Google grant/API保管は別管理、proxy未実装 |

## 二つの認可とGCP

| 認可 | 担当と今回の方式 |
|---|---|
| AP → Google | 利用者がGoogle account/scopeを確認してConnectionを認証。AP標準OAuth中継でAP側が用意したGoogle appを利用 |
| cmdbox → AP | 提供側がAP public client/PKCE/callback/bindingを実装し、利用者が自分のAP projectをAuthorize。scope=mcp。Google clientとは別 |

この標準中継経路では、実ユーザーごとのGCP project・Drive API設定・Google client ID/secret作成を利用開始の必須作業にしない。Google OAuth app自体が不要になるわけではなく、AP側のappを使う。組織の許可、scope、credential保管、外部中継への通信条件は確認する。他版・配置・企業policyでも必ず使えるという保証ではない。

本番では、AP標準中継、提供側の独自Google app、顧客専用appを選べる設計が候補。独自方式では担当主体がGCP/client/branding/必要な審査/secret管理を担う。今回の成功を独自client方式の実証と扱わず、利用者一人ずつにGCP作成を求める設計とも混同しない。

標準 `drive` は全Driveを閲覧・管理できる広いrestricted scope。flowが読取でfolderを固定していてもGoogle grantはfolder限定にならない。狭いscopeやPicker方式への変更は別設計・未検証。[Google公式scope説明](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)

## Replyの失敗と修正

schema27の `{{step_1}}` はstep state全体を参照する。filesへ入れると配列でなくobjectになり、アプリの型・20行上限チェックが `drive_result_limit_exceeded` で拒否した。多数のファイルが返ったという意味ではない。標準Drive actionは配列を返すので `{{step_1['output']}}` が正しい。

Mode=AdvancedのResponseはJSON editor。UIへ入れるのは次の本文だけで、外側のresponse wrapperを付けない。APIではdynamic propertyにより `input.response.response` に置かれ、SDKは既知wrapper一つだけを解く。

```json
{
  "contract": "drive-search-metadata-v1",
  "policyId": "DUMMY-DRIVE-POLICY",
  "completion": "unverified-by-stock-piece",
  "files": "{{step_1['output']}}"
}
```

説明用DUMMY例であり実import用ではない。builder・receipt検証・disabled templateを修正。networkなしの独立containerで実AP imageの式resolverと公開MCP Replyへdummy配列を渡し、旧式の同じ失敗と修正式の成功を再現した。stock契約回帰18件、元台帳の実1→2とdummyの3回目拒否、lint65 files、固定cmdbox patch replay4 filesも確認。mock96件・実ADK dummy7件・native history保持2ケースは先行する別記録。

## Publishと有効化を分けた診断

本人のPublishはUIで `fetch failed` を表示したが、修正版は新published版のLOCKED/validとして保存済み、flowはDISABLED、draftなしだった。ログで確定したのはtrigger有効化のfetch失敗まで。送信先・根本原因は未特定。

検証済み公開artifactをオフラインでworker cacheへ復元し、独立開発用OAuthで `ap_flow_structure` / `ap_read_step_settings` を実行。再編集・再Publishをせず `ap_change_flow_status(ENABLED)` が成功した。元cacheへ戻した後もENABLEDを確認。cache復元後の成功だけから通信先の原因を断定しない。Google stepの灰色表示・空panelは未解決で、実action成功とは別に残す。

## 管理MCPと通常runtime

固定CEにも公式ap_*管理toolsがあり、今回tools/listで42個を実測した。MCPで編集できないという制限はない。必要な更新には `ap_update_step` / `ap_lock_and_publish` も正規経路として使える。[固定builder](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/server/api/src/app/mcp/mcp-server-builder.ts)、[公式MCP概要](https://www.activepieces.com/docs/mcp/overview)

開発operatorの短期接続と通常cmdboxの `lab_drive_search` 限定を分離した。通常allowlistを広げず、管理者JWT抽出・再利用、DB直接書換え、同名flow追加作成/削除、Test step/flowは行わない。scope=mcpはtool単位の最小権限ではなく、提供側brokerのUID/project/flow/引数/generation制御が残る。CEの管理MCP成功をSSO/embedding/service API key等の有償機能の成功と扱わない。

## 終了を三層に分ける

1. app → AP：通常revoke、local access/refresh/pending/lease除去、app/worker/callback停止。最終snapshotでactive0を確認。
2. AP Connection：Google credentialの記録はACTIVEで保持。削除は今回の終了対象外。CEのConnection削除はAP側記録削除で、Google revokeの証明にならない。
3. Google grant：本人Google Accountの該当app access解除は別で、今回は未確認。標準共有appでは同じGoogle accountの他接続への影響を確認して行う。[Google公式解除手順](https://support.google.com/accounts/answer/13533235?hl=ja)

実値・token・メール・内部project/file IDs・未編集log・AP snapshotはignored/privateのみ。公開資料はcounts、テスト用ファイル名、経路、状態を記載する。停止済み内部HTTP境界試験は再作成せず、未分類失敗を隔離成功にしない。この結果の公開範囲はsanitized文書/sourceに限る。Space整理は別担当。

## 再現の区分

公開再現はREADMEのdummy-only手順とdisabled templateで行う。実Google再現には対象利用者/project/Connection/flow/published版/folderを非公開manifestへ固定し、本人Google/AP同意、通信先・期間・終了の明示承認が必要。今回の失効grant・終了済み通信枠・消費済み2/2台帳を再利用/リセットしない。自然言語LLM、企業policy、production vault/TLS、多host/多利用者は別の受入条件。
