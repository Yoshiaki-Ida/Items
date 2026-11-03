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

## 確認してから登録

次は接続先のプロジェクトとトラッカーIDへ置き換えてください。

```powershell
.\scripts\run_meeting_importer.bat dry-run `
  .\samples\meeting-open-items.json .\config\config.json `
  my_project 6 20 .\output\preview.json
```

接続先、件名、件数、担当者、期限、`unset_custom_fields`、`unresolved_mappings`、`skipped_items`、`warnings` を確認します。
入力・設定・接続先を変えたらdry-runをやり直します。
確認後にのみ次を実行します。CLIは人間の承認を自動判定しません。
Agent経由ではdry-run後の別メッセージ「Redmineへ登録して」が必須です。

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