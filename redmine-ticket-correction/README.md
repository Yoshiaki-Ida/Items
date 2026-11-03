# Redmine Ticket Correction

会議JSONから親子チケットを登録し、Markdownへ再出力して確認するツールです。
文字起こしの解釈は行いません。議事録生成には別配布のSkillを使用します。

## 導入

Windows / PowerShell 5.1以上 / Python 3.11以上が必要です。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .\config\config.example.json .\config\config.json
```

既存の `config/config.json` は上書きしないでください。
`redmine_url` はサブパスも含むRedmineのURLです。`verify_ssl` は通常 `true` を維持します。
社内CAは `ca_bundle` へCA証明書ファイルのパスを設定します。
`custom_field_ids`、`user_ids`、`status_ids`、`priority_ids`、`version_ids` は名称と数値IDの対応です。
空の対応表は記入前の状態です。dry-runで不足を確認し、必要な項目を登録します。
担当者は完全一致、空白除去一致、名字一致の順で解決します。同姓対策にはフルネームを使ってください。

APIキーは設定JSONやチャットへ書かず、自分のPowerShellでユーザー環境変数へ登録し、VS Codeを完全に再起動します。
以下はプレースホルダーです。キーを含むコマンドを資料やソースへ保存しないでください。

```powershell
[Environment]::SetEnvironmentVariable("REDMINE_API_KEY", "<your_api_key>", "User")
```

## 入力と出力

入力はSkillが生成するSchema v1.6の `redmine-import.json` です。
`samples/meeting-open-items.json` は架空の最小例です。
出力の既定値は `output/redmine-ticket-creation/<project>/` 配下です。
出力先を指定すればその場所を使用します。APIキーなしのdry-runは通信しません。
結果JSONと同じ場所に、拡張子を`.html`にした登録プレビューも生成します（`preview.json`なら`preview.html`）。
登録プレビューは実際の登録予定データから生成した最終本文の確認用です。議事録HTMLとは別に開いてください。まだRedmineには登録されていません。

## 確認してから登録

専用Agent `redmine-meeting-orchestrator` は、議事録生成Skill `create-auditable-meeting-minutes` を使い、登録ドラフト（dry-run）の提示まで進めて停止します。Skill単独では登録しません。

プロジェクト名と、そのプロジェクトで有効な親・子トラッカー名から選べます。手動で候補を取得する場合は次を使います（環境変数のAPIキーが必要、GETのみで登録はしません）。

```powershell
.\scripts\run_meeting_options.bat --config .\config\config.json --output .\output\registration-options.json
.\scripts\run_meeting_options.bat --config .\config\config.json `
  --project-name "<候補から選んだプロジェクト名>" --output .\output\registration-options.json
```

最初に一覧から選び、次の取得で表示されたトラッカー候補から親・子を選びます。同じコマンドに`--parent-tracker-name "<親の名称>" --child-tracker-name "<子の名称>"`を追加するとIDへ解決できます。同名・候補なしの場合は停止して確認し、プロジェクトは`--project-id`でも絞れます。取得した候補は参照可能なプロジェクトと有効トラッカーであり、登録権限の保証ではありません。一覧のページングは自動処理します。

確認済みIDの直接指定も引き続き使えます。次のIDは、自分の接続先で確認した値へ置き換えてください。

```powershell
.\scripts\run_meeting_importer.bat dry-run `
  .\samples\meeting-open-items.json .\config\config.json `
  my_project 6 20 .\output\preview.json
```

`output/preview.html`を開いて、接続先、親子の件名・最終本文・件数、担当者、期限、設定不足・警告を確認します。JSONも機械用証跡として保持します。`unset_custom_fields`、`unresolved_mappings`、`skipped_items`、`warnings`に意図しない項目があれば、修正して再ドラフトします。
名称候補JSONを使う場合は、BAT第8引数を`""`（URL上書きなし）、第9引数を候補JSONのパスにします。CLIでは`--registration-options`を使えます。接続先・プロジェクト・トラッカーIDが候補と不一致なら停止します。名称は取得時点の情報です。候補なしの直接ID指定では名称未取得と表示します。
入力・設定・接続先・候補を変えたら登録ドラフトを作り直し、再承認を受けます。
確認後にのみ次を実行します。CLIは人間の承認を自動判定しません。
Agent経由ではdry-run後の別メッセージ「Redmineへ登録して」が必須です。
提示と同じターンの自動承認、単なる了解、質問・修正依頼では登録しません。

本文の未設定値（null）は空項目の見出しごと省略し、チケット自体は保持します。理由・背景と、構造化された時刻・話者・要旨の根拠を空行で分けます。根拠と同一の末尾表記は重複させず、期待状態や実名を推定して補いません。

```powershell
.\scripts\run_meeting_importer.bat apply `
  .\samples\meeting-open-items.json .\config\config.json `
  my_project 6 20 .\output\apply.json
.\scripts\export_tickets.bat `
  "https://redmine.example.com/redmine" my_project "*" .\output\tickets.md
```

`failed_items` が空であることと、作成・更新されたID・件名が再出力結果にあることを確認します。
失敗後は結果を確認せず再送しないでください。重複時にはCLIが処理方法を確認する場合があります。

## 補助機能

既存親へMarkdown/YAMLから子だけを追加できます。標準の会議フローとは独立しています。
次のコマンドは実登録です。入力と親IDを確認してから実行してください。

```powershell
.\scripts\create_children_from_markdown.bat 1 Task `
  .\samples\child_items.yaml "https://redmine.example.com/redmine" my_project
```

補助CLIの `--dry-run` は既存チケット・トラッカー確認のため通信するのでAPIキーが必要です。
証明書を無条件に無効化せず、承認済みの接続先とCA設定を使ってください。

## テストと制約

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

テストは模擬APIを使い、実Redmineを書き換えません。
Skillとの結合テストは `shared-skills` のREADMEを参照してください。
音声解析・Jira分析・品質分析は対象外です。AIの抽出結果と日付・担当者は人が確認します。
実サービスの権限、プロジェクト・トラッカー設定、実会議の抽出精度は導入先での検証が必要です。
401/403や古いAPIキーのエラーでは処理を止め、キーとVS Code本体の再起動を確認します。
入力・設定・生成物はGit管理外に保存してください。

確認済み接続設定の`verify_ssl: false`はそのまま使用し、許可を毎回聞き直しません。未設定の接続先を勝手に検証無効にせず、既定は`true`です。ブラウザの警告無視は設定変更の許可にはなりません。証明書検証の無効化は接続の安全性を保証する運用ではありません。APIキーを送信する接続先と設定の管理責任を確認してください。
