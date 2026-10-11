# 公開candidateの確認

含めるものはdummy-only adapter/test、固定version/hash lock、2ファイルpatch、Docker/config template、設計と集約レポート、上流noticeです。上流source本体、wheel、venv、binary、実env、private、本人メール、machine名、個人path、実AP IDs、OAuthclient/grant/token、生ログ、停止済み内部HTTP試験の再実行codeは含めません。

Gitの追跡候補と全local履歴を`tools/scan_public_candidate.py`で確認します。JWT/known secret format/private key、実個人path、想定外email、停止済み試験file名、binary/巨大file等を検査し、値はreportへ出しません。literal DUMMY値と固定hashは別扱いです。pattern scanだけで全secretを保証できないため、明示allowlistのexportと目視確認も行います。

履歴は新規local repositoryとして開始し、古いtask履歴を取り込みません。GitHub認証account名やlocal commit identityは公開資料へ埋め込みません。外部repo作成/pushは最終candidate確認後に行います。CIでAP起動、secret/grant生成、外部provider操作を自動実行する構成はありません。
