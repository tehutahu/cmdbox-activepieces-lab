# 検証レポート

最新（2026-10-12）は[標準Drive E2E](GOOGLE-DRIVE-E2E.md)：native cmdbox→Redis→worker→実ADK scripted→AP標準Driveで実2件取得、元台帳2/2と終了を確認。自然言語LLMは未検証。以下のphase2/公開baselineは保存時点の履歴。[最新JSON](google-drive-e2e-summary.json)

最新のphase2では、単体回帰67件・実ADK offline dummy7件、native mock経路を確認した後、本人認可したA/Bで新adapter→実APの限定統合を実行しました。各UIDでflow二回・refresh一回・通常revoke・native拒否が成功し、本人UI witness二件と専用停止・秘密整理まで確認しました。[実AP/Mock/未検証の区分](PHASE2-VALIDATION.md)と[最新集約JSON](phase2-validation-summary.json)を参照してください。

phase1のoffline32 unit/integration + 実ADK dummy7、実アプリ11、[継続12 scenario group](CONTINUATION.md)は別の履歴です。2 Web/worker processの共有guard検証はphase1のmockであり、phase2新OAuth bootstrapの複数process成功ではありません。以下は公開baseline時点の既存記録です。

2026-10-11、固定版を使ったWindowsローカル検証。非公開業務アプリ、Google/Slackの実credential、業務data、外部LLM inferenceは使っていません。実AP試験の生証跡は元の非公開検証workspaceに保持し、この公開candidateには集約結果だけを載せます。

## 過去の実AP CE / MCP試験

| 項目 | 観測した事実と限界 |
|---|---|
| 個人project | A/Bは別MEMBER・別PERSONAL project。同platformでautoCreatePersonalProjects有効。CEのuser-limit bypassもsourceで確認。大量user負荷は未検証 |
| flow配布 | lab ownerの正規USER sessionで合成templateのimport/validate/publishと再実行差分ゼロを確認。CEの正式service API key、組込SSO/embeddingの利用を示す結果ではない |
| 本人MCP認可 | 本人操作によるproject-scoped grantを使用。正規userinfo subject、token claims、grant metadataのproject整合を照合。共通admin tokenへの代替なし |
| 通常MCP境界 | own discovery/callは合成marker。他projectのraw toolはunknown、flow structure/testはFlowNotFound、他project追加runはゼロ。通常対象APIに限る結果 |
| 実ADK＋実AP | 当時有効な本人grantで8シナリオ通過。app UIDは合成値で、実cmdboxログインは未接続 |
| management tools | 本人project tokenでも42のraw management toolsを列挙。mcp scopeを検索専用flow権限と見なせない |
| grant終了 | 対象2grantは正規revoke API成功と有効metadata一覧の不存在で失効を確認。local token削除。旧token拒否probeは未実施 |

公式piece packageを過去の実験で扱いましたが、この公開repositoryにはpackage、upload機能、認証client/account情報を含めません。

## 境界の未解決事項と停止した試験

外側ingressの通常Webhook route拒否と、AP内部からの実行制御は別の境界です。過去の確認では内部の匿名Webhookから合成flowが動作しました。その後の内部HTTP追加試験は未分類失敗でHTTP statusも得られず、隔離成功・迂回成功のどちらも証明できません。停止指示により終了し、再実行・別経路debugのcodeはこのrepositoryへ入れていません。この制約は解決済みとして扱いません。

## 独立UID adapterの合成試験

28件のunit/integrationと実ADK7シナリオ、計35件が通過しました。署名改変、payload改変、TTL、replay、UID/app/session不一致、LLMのUID指定、cached A toolのB実行、binding generation変更、切断中の戻り値等を拒否します。実AP、実Redis、実credential、外部socket接続は使いません。

## 実cmdboxアプリ経路のLOCAL MOCK

実HTTP password route、starsessions RedisStore、WebSocket、Redis queue、native AgentChat worker、実ADK DatabaseSessionService/Runner/tool実行を使う11シナリオが通過しました。

1. 未ログインと誤passwordを拒否し、OAuth routeはmountしない。
2. A/B/Cのserver session UIDを分離。
3. 実Web→Redis→worker→ADK→dummy toolでown markerのみを返す。
4. 同じchat IDの反復でもUID別SQLite履歴と一覧が混ざらない。
5. UID/project query指定で主体を変更できず、BはA専用履歴を読めない。
6. 未接続Cはmodel/tool前にreconnect_required。
7. DUMMY形式bindingだけをSQLiteへ保存し、別instanceで復元。
8. A切断後もBだけが継続。
9. app再起動後も履歴と切断状態が残る。
10. 明示した合成再接続はgenerationを増やす。実grant作成なし。
11. traceでnative段階・allowlist・禁止socket試行ゼロ・正常停止を確認。

password/cookie/signing keyは公開literalなので、この成功は本番認証の安全性を証明しません。LOCAL MOCKはmodel、MCP transport、credential provider、limiter planを合成実装へ差替えています。最小native routeだけを起動し、標準管理UIと全APIの隔離は未検証です。この11件自体は新adapter＋実APの結果を含みません。後続phase2の実AP結果は上記の別記録に分けています。

初期の失敗実行では依存import時のtokenizer取得がsocket制限に阻まれました。固定hashの公式assetをsetup時に配置後、通過実行では禁止socket試行ゼロでした。

## 再現範囲

commitしたsummaryは個人識別子、生ログ、secretを含まない集約です。test実行時の詳細JSON/trace/SQLiteはGit対象外の`evidence/`等へ保存します。新しい実AP初期化・grant取得・Google/Slack接続は通常mock再現に含めません。
