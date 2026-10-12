# 公開candidateの確認

含めるものはdummyをdefaultとするadapter/test、明示承認用の限定OAuth/broker/cleanup operator、固定version/hash lock、4ファイルpatch、Docker/config template、設計と集約レポート、上流noticeです。上流source本体、wheel、venv、binary、実env、private、本人メール、machine名、個人path、実AP IDs、OAuthclient/grant/token、生ログ、停止済み内部HTTP試験の再実行codeは含めません。

Gitの追跡候補と全local履歴を`tools/scan_public_candidate.py`で確認します。JWT/known secret format/private key、実個人path、想定外email、停止済み試験file名、binary/巨大file等を検査し、値はreportへ出しません。literal DUMMY値と固定hashは別扱いです。pattern scanだけで全secretを保証できないため、明示allowlistのexportと目視確認も行います。

履歴は新規local repositoryとして開始し、古いtask履歴を取り込みません。GitHub認証account名やlocal commit identityは公開資料へ埋め込みません。phase1は既に公開済みです。追加公開はレビューと明示指示を受け、sanitized source/docsを作業branchへcommit/pushします。mainへのmergeやdeploymentはこの作業に含めません。CIでAP起動、secret/grant生成、外部provider操作を自動実行する構成はありません。

今回の公開候補には[phase2の集約結果](phase2-validation-summary.json)、[標準Drive E2Eの集約結果](google-drive-e2e-summary.json)、[最終offline検証](public-reference-checks-summary.json)を含めます。実testのprivate root、個人path、実subject/project/client/grant、本人Network Response、DPAPI file、SQLite、生ログ、browser cookie/tokenは含めません。全履歴pattern scanに加え、非公開照合metadataの既知識別子と候補/履歴の一致を値を出さず点検します。scanはすべての未知secretや個人情報を検出する保証ではありません。
