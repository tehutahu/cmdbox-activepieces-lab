# 上流と依存ライセンス

cmdbox patchには公開MITコードの文脈を含むため、[固定commitのlicense](https://github.com/hamacom2004jp/cmdbox/blob/a429260512035aa358d49e7b319c2bfc56532742/LICENSE)を`third-party/cmdbox-LICENSE.txt`へ保持しました。

Activepiecesは[固定commitのlicense](https://github.com/activepieces/activepieces/blob/d125d34e59ac57ea4d0df57af4b917344027f06b/LICENSE)で、CE領域のMITとEnterprise領域の別licenseを区別します。EE codeや公式piece packageはvendorしていません。Docker imageを自己のlicenseとして再配布する構成でもありません。

Google ADKは[2.8.0のApache-2.0](https://github.com/google/adk-python/blob/v2.8.0/LICENSE)。公式wheelをsetupで取得し、このGit repositoryにはbinaryを含めません。Python overlayを含むeffective依存の宣言licenseは`dependency-licenses.json`へ記録します。wheel metadataによる宣言の確認であり、組込み第三者code全体の法的適合を保証する監査ではありません。UNKNOWN/複数licenseがあれば個別確認対象です。

このlab独自コードのlicenseはユーザーが未選択です。保守的なdefaultとして、新たなMIT等の利用許諾を勝手に付与しません。既存upstream licenseは変更せず、独自codeの再配布・商用利用を明示許諾する場合は公開前または後続commitでlicenseを選択してください。

## 依存宣言の確認結果

G側で再構築したeffective Python118 packageを確認し、宣言licenseのUNKNOWNは0件でした。psycopg、psycopg-binary、psycopg-poolはLGPL-3.0-only宣言です。このrepositoryはそれらのbinaryを配布せず、hash lockから取得します。将来binaryやimageを自ら再配布する場合の義務を、このmetadata点検だけで解決済みとは扱いません。
