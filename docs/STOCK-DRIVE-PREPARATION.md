# 標準Driveの本人認可前準備

途中の準備記録です。最終は[実E2E](GOOGLE-DRIVE-E2E.md)：標準中継・実2件・元台帳2/2・AP grant失効・通信/cache復旧完了。下記のown-client/GCP前提・未実施・承認待ちは当時の計画で、現在の必須手順ではありません。

状態: 標準Google Drive0.11.0とZIP2.8.29を専用AP CE0.92.2の実worker cacheに準備し、公開npm artifactのSHA-512、標準bun install --ignore-scripts、entryロード、drive_search_filesの存在、ready markerを確認した。Google API actionは実行していない。

既存dataは新しいignored/private退避へ保存し、networkなしの独立コピーで81 tables・catalog13,475件を確認した。専用AP/helperを通常再作成し、APの同期NONE・STRICT・内部network接続を維持。APに公開されたportは元の専用入口だけ。TLSを終端しない所有relayに限定したDNS mappingとSSRF single IP追加だけを一時適用した。OS/global Docker/CA設定は変更していない。

npm準備後はrelayのregistry.npmjs.org upstreamを閉じ、oauth2.googleapis.comとwww.googleapis.comだけに切り替えた。relayは最大2時間で自動停止する設定で、期限は2026-10-12 08:59:29 UTC。このtimerは通信を閉じる機能であり、元AP env/hosts/networkの復帰操作を代行しない。専用restoreコマンドとcache archiveをprivate記録に保存した。

本人のsecret入力、Google/APのAuthorize、新Connection、固定flowのpublish、実Drive検索は未実施。標準Drive scopeは広く、folder queryはGoogle grantの権限制限ではない。実flowの承認予算は2回、最大2時間。永久削除は承認されていない。

次は専用Google OAuth Web clientをTestingで本人だけに設定し、B projectのCustom OAuth2 App (Advanced)に本人が入力する。Google redirectはhttp://localhost:18088/redirect。その後にConnection ref・固定folder・MCP archive・flow ID・published version・raw tool nameを照合し、Bだけのstock設定を有効化する。既存owner JWT抽出・再利用は承認レビュー拒否後、停止したまま。停止済み内部HTTP boundary probeは再作成していない。

sandbox内Google通信、actual appと新B Connection/flowの結合、実検索結果、remote revoke後の状態と終了時network復帰は未検証。準備packageのロード成功をそれらの成功として扱わない。

本人UIのGoogle OAuth app作成手順は[Google公式Drive quickstart](https://developers.google.com/workspace/drive/api/quickstart/js)に基づく。秘密とfolder/file/subject/project識別子はprivate記録だけに保存した。既存staged変更を維持し、この追加をcommit/push/PRにはしていない。

公開candidate131 files・全local Git historyのblob/commit72 objectsを、既知private ID/secret11値とcredentialパターン・2MiB以上のartifactについて走査し、該当0件。Git whitespace、Python helper AST、Node準備script構文も通過した。これは既知値・patternの確認範囲であり、全種類の秘密検出保証ではない。

appの認可開始が後でも今回のrelay期限を延長しない。既存終了時history purgeはread-only保持へ変更済みで、所有metadataをprivateに保持する。実appはまだ起動していない。


## 本人待ちまでの追加照合

既存MCP0.0.21のDB archiveは保存済み公開npm artifactとbyte/SHA-512一致。追加依存・scriptなし。既存B project/platform一致をofflineで確認し、registry閉鎖を維持したまま標準実cacheへrehydrateした。mcp_tool/reply_to_mcp_clientと必要propsをロードできた。固定flow候補は実APのIMPORT_FLOW API schemaと実MCP/Driveの3step/input propsに一致した。未作成Connection refとpublished flowの照合は本人操作後に残る。

実stock launcherの自動終了はhistory削除からread-only所有確認/保持へ変更した。native Web/Redis/worker/ADKの2ケースで、通常期限停止とrevoke失敗停止の前後にsession/event/app/user stateの全行が一致。token除去とworker/listener停止は維持。default dummy96件＋実ADK dummy7件、stock契約17件、lint65 files、公開patch適用4 filesが成功。変更前コピーと追加cache archiveはprivateに保存した。

本人は今、AP sign-in/ConnectionsとGoogle Cloud own-client画面を開ける。実cmdbox app側のAP Authorize入口はまだ未起動で、Connection/flowの照合後にだけ使う。Connections一覧UIのcatalog latest0.11.3と固定0.11.0のOAuth2 URL/token URL/scopesは一致した。実検索flowは0.11.0固定である。

最大期限08:59:29 UTCに向け、元構成への復帰helperを08:56:29 UTC開始でARMEDにした。委任threadではCodex automationが未対応だったため専用hidden local processを使う。実際の復帰完了は期限時の別確認が必要。新flow/Connection/Google/AP grantの本人終了をこのhelperが代行することはない。


## 2026-10-12 20:00 JST終了時の実測結果

この節が上記の準備段階の未実施記録を更新する。本人が標準Google Drive Connectionを保存し、Bの既存flowをPublish、cmdboxからAP Authorizeを完了した。新しいOAuth client/API keyは発行していない。

native cmdbox login → Web websocket → shared Redis → native worker → actual ADK scripted model → AP published standard Drive flowを1回実行した。返却配列の契約検査で `drive_result_limit_exceeded` となり、期待する2ファイルの名前は取得できなかった。実Google LLM inferenceは使っていない。生レスポンスは保存していない。

固定CE0.92.2のschema27ではlegacy式 `{{step_1}}` がstep state全体を参照する。標準Drive actionはファイル配列をreturnするため、Replyの `response.response.files` は `{{step_1['output']}}` が必要。公開候補のbuilder/receipt検証とdisabled dummyテンプレートをこの式へ修正した。stock dummy17件、lint65 files、固定cmdbox patch replay4 filesが成功。実flowの修正版Publish・再認可・成功検索は未検証。

本人の重複flow削除後、元の許可済みflow IDは存在しENABLED、所有者も一致。同名flowは公開版・最新draftを含めて1件、別IDの同名flowは0件。元の公開版IDは変更されずReply式は旧式のまま。追加Import・flow復元・2回目の検索は行っていない。

実検索は上限2回中1回のみ。token交換枠1/1も消費済みのため、既存アプリへの再Authorizeは予算で拒否される。再試験には交換再試行と通信期間の承認、旧runtimeを可逆退避する通常のfresh bootstrap、消費済みflow予算1の引継ぎ、修正版の既存flow Publish、本人の新AP Authorizeが必要。予算リセットやtoken/codeの手渡しで迂回しない。

19:57 JSTに期限終了処理が開始し19:57:31 JSTに元AP/helper env・hosts・network・image・mountの復旧を検証。20:00 JST後の独立検査14項目も成功し、専用relayと一時bridgeは存在せず、アプリcallback/Web listenerも停止。worker停止、local token削除、履歴metadataのread-only保持を確認。永久データ削除は行っていない。

19:56頃の停止中整合snapshotでは、Bの当該public clientのAP grant記録3件はすべてrevoked、active0件。B所有の標準Drive ConnectionはCLOUD_OAUTH2/ACTIVEの1件として残る。AP grant失効、AP Connection残存、Google側grant失効は別の状態であり、Google側失効は確認していない。Connection・flow・Google grantを自動削除/失効していない。

停止済み内部HTTP boundary probeは再作成していない。owner JWT抽出/再利用の承認拒否は維持。native browser automationはWindows実行kernelの起動エラーで使えず、UI灰色表示の原因は未解決。main/既存staged作業を保持し、今回の変更をcommit/push/PRにしていない。秘密・個人ID・生ログはignored/privateだけに保存。
