# 独立 metadata readonly 検索 piece のローカル実装

通常利用している Google account を対象とする本人の選択を反映した、**未導入・未認可のローカル成果**です。対象 account の識別情報や folder は未選択です。connected app の account を推定して使っていません。既存 [stock 準備](DRIVE-SEARCH-PREPARATION.md) と phase2 の90公開候補ファイルを変更せず、追加 source と別差分でレビューします。

## 固定した identity と取得 contract

| 項目 | 値 |
|---|---|
| 独立 package | `@cmdbox-lab/piece-drive-metadata-search` / `0.1.0` |
| 対象 AP | CE `0.92.2` / public commit `d125d34e59ac57ea4d0df57af4b917344027f06b` |
| framework | 上記 commit の `0.40.0` source、context version `2` |
| action | `search_folder_metadata` のみ。trigger なし |
| scope | `https://www.googleapis.com/auth/drive.metadata.readonly` 一つ |
| model alias | `lab_drive_metadata_search`。入力は空 object のみ |
| operator input | 明示 folder ID、固定 filename term、policy ID、総行数1–20、ページ数1–5 |
| provider output fields | `nextPageToken,incompleteSearch,files(id,name,mimeType)` |
| model output | id/name/mimeType と完了状態のみ。policy、page token、credential、Connection、folder ID は渡さない |

[Google scope](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) は、アクセス可能な Drive metadata 全体を許します。folder 条件は操作上の絞り込みで、OAuth 権限境界ではありません。内容読取/download/upload 用 scope は宣言していません。stock の広い `drive` Connection は使用しません。

[action source](../pieces/drive-metadata-search/src/index.mjs) と [search contract](../pieces/drive-metadata-search/src/search.cjs) は次の request に限定します。

- `GET https://www.googleapis.com/drive/v3/files`、`corpora=user`、`spaces=drive`、Shared Drives 無効。
- 明示 folder の `'id' in parents`、`trashed = false`、folder MIME 除外、`name contains` の固定 term。quote/backslash を literal として escape。任意 q、URL、fullText、再帰、shortcut target の追跡はない。
- 一回最大5行、残りの総予算に合わせて pageSize を縮める。総最大20行、最大5 request、各 request timeout 8秒、JSON body 最大64 KiB。redirect を拒否し、自動再試行しない。
- 空/短いページでも nextPageToken があれば続行。API の `incompleteSearch` を全ページで OR 集計し、残 token と予算到達を未完了として返す。token loop、不正 flag、超過、重複 ID、未知 field、credential/content 混入は失敗させる。失敗時に途中結果を成功として返さない。

[files.list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list) と [query literal/parents 仕様](https://developers.google.com/workspace/drive/api/guides/search-files) を確認しました。`complete=true` は、この固定 query が予算内で API の終端に到達し、API が incomplete としなかった意味です。同時更新に対する snapshot、一切の取りこぼしがないこと、folder の存在/所有、Drive 全体の網羅性を保証しません。拒否された page token は sanitized failure とし、同じ invocation 内で再取得して完了扱いにしません。

`stopReason` は `complete / row_limit / page_limit / incomplete_search`。`incompleteSearch` と `truncated` は別 bool で、両方が同時に true の場合も表現します。piece から broker へは検査用 `pagesRead/rowsRead/policyId` も返し、model へ投影する際に除きます。filename は信頼できない metadata です。外部 LLM を呼んでおらず、本番 model の prompt injection 耐性は未検証です。

## 固定 source と実行形状

registry の framework `0.40.0` は HTTP404、公開 version 一覧に AP `0.92.2` と同じ shared dependency の版もありませんでした。別版に置換せず、同じ public commit の `packages/pieces/framework`、`packages/core` から bundle を作りました。source の Git blob hash を固定 tree と照合します。大規模 source、dependencies、bundle、tgz、詳細証拠は ignored `runtimes/` または `local-review/` のみです。

[build utility](../tools/build_drive_metadata_piece.py) は独立 source と pinned framework を self-contained CommonJS に bundle し、固定 [engine extraction](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/core/shared/src/lib/automation/pieces/utils.ts) を実行します。`constructor.name=Piece`、唯一の action、scope、AP min/max `0.92.2`、context `2` を検査しました。通常 dependency は reviewed [exact lock](../pieces/drive-metadata-search/build-dependencies.lock.json) のみ。npm cache/runtime は G 内、install scripts 無効。AP/npm へ publish しません。

固定 [piece executor](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/server/engine/src/lib/handler/piece-executor.ts) は auth を `context.auth` と `propsValue.auth` の両方へ渡すため、その一致を検査して auth を入力から除きます。固定 [OAuth response formatter](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/packages/server/api/src/app/app-connection/app-connection-service/oauth2/oauth2-util.ts) は scope を top-level に残し data から除きます。action は own-client `type=OAUTH2` と top-level scope の完全一致を必須にし、欠落/広い scope では Google I/O 前に停止します。実 Google refresh 後の response と AP 側保持は未検証です。refresh response に scope がない場合の upstream merge は source 観察に留めます。

bundle は Activepieces MIT 対象 framework/core だけを使用します。upstream [license notice](../third-party/activepieces-framework-LICENSE.txt) を保持し、archive には bundled dependencies の LICENSE も同梱します。EE implementation は bundle に含めません。lab 独自 license は未選択のままで、既存 cmdbox notice も保全します。

## UID/alias のレビュー用登録

[registration template](../templates/drive-metadata-registration.json) は `enabled:false`、全 identity が DUMMY です。[registration/broker](../poc/cmdbox_gateway/metadata_drive.py) は独立 package/version/action/scope、UID、subject、project、flow ID、raw name、policy、folder、term を固定し、既知以外の field/重複を拒否します。既存 production の `lab_identity` schema/bootstrap は変更していません。この登録はレビュー gate と明示 factory 注入の準備であり、live activation ではありません。

呼び出しは checked login UID→signed Redis job→verified worker invocation→実 ADK の UID/session→subject/project/flow binding→AP credential reference/grant/generation→empty-argument raw tool の順です。management alias、query/Connection/UID 引数、旧 generation を upstream 前に拒否し、返却前も generation を確認します。SDK session は毎回新規で、結果 cache はありません。tool schema の追加 input property も拒否します。Google token は AP Connection から provider request にだけ渡し、cmdbox 側には AP token だけを置く設計です。

[flow preparation](../templates/drive-metadata-flow-preparation.json) は `IMPORT_FLOW` request / schema `27`、MCP piece `0.0.21`、固定 custom action、advanced reply `{response: step_1}` です。全 step `valid:false`、Connection 等 DUMMY のまま。本人 project に import 済み、publish 済み、Google Connection 作成済みとは扱いません。実 raw name は本人 project の discovery 後に固定します。

## 検証と再現

新規 search contract **15試験**、UID/SDK/registration/template **11試験**、native **4 outcome group**。native は Web password login→WebSocket→共有 Redis→native worker→実 ADK→公式 MCP SDK→**実 bundle action**→fake Google page を通りました。

- A/B は同 chat ID でも各自の合成 file のみ。fake store の別 folder、nested、trash、folder record を除外。
- A は空ページから続行して complete、B は incompleteSearch を明示して未完了。native raw call 4回で fake page request は計6回。
- fake refresh 後の generation で成功。fake A revoke 後は I/O 前に拒否、B は継続。旧/別UID/subject/project/flow、途中 revoke、foreign policy、余計な input/credential を契約試験で拒否。
- Python harness は専用 localhost app/Redis のみ許可、Node fixture は fetch を置換し net/TLS socket を拒否。禁止 socket 試行0。起動した process/worker は停止。

```powershell
# 復元先は lab の ignored runtimes。既存フォルダを上書きしない。
# build-dependencies.package.json -> package.json、lock -> package-lock.json を fresh dir へコピー。
# npm ci --ignore-scripts --no-audit --no-fund --cache <G内cache> をその dir で実行。
.\runtimes\python312\python.exe -B -X utf8 tools\build_drive_metadata_piece.py `
  --node 'C:\Program Files\nodejs\node.exe' --dependencies runtimes\drive-piece-deps `
  --source-cache runtimes\activepieces-piece-source
& 'C:\Program Files\nodejs\node.exe' --test pieces\drive-metadata-search\test\search.test.cjs
# build output の明示 path。既存 mock Redis と、空の18090が必要。
$env:CMDBOX_LAB_NODE_PATH='C:\Program Files\nodejs\node.exe'
$env:CMDBOX_LAB_METADATA_BUNDLE='<build output>\package\src\index.js'
.\runtimes\python312\python.exe -B -X utf8 poc\test_metadata_drive.py
.\runtimes\python312\python.exe -B -X utf8 app-lab\test_metadata_app.py
```

これは local bundle/extraction/action と native app mock の証拠です。全体 dummy suite は90試験と実 ADK offline 7 outcome が成功しました。集計は [sanitized summary](drive-metadata-custom-piece-summary.json) に記録します。AP の archive extraction、installed metadata、sandbox runtime、実 flow import/publish、実 own-client UI/state/Google token/refresh/revoke、通常 account の実 metadata/Google ACL は未検証です。live alias の production schema/bootstrap 接続と、対象 flow/Connection/公開版の照合も残ります。適用対象・本人操作・承認事項は [適用 review](DRIVE-METADATA-APPLY-REVIEW.md) に具体化しました。
