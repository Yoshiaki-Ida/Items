# Items

会議記録を確認してからRedmineへ反映するためのプログラム集です。
初版は [redmine-ticket-correction](redmine-ticket-correction/README.md) のみを収録します。

文字起こしからの議事録生成は、別リポジトリ
[shared-skills](https://github.com/Yoshiaki-Ida/shared-skills) のSkillとAgentを使用します。
本リポジトリには、社内向け導入資料・実会議記録・ローカル接続設定は含めません。

## セットアップ

Windows、Git、PowerShell 5.1以上、Python 3.11以上を用意します。
Agentの実行にはVS Code版GitHub Copilotと、会議資料をAIへ渡すことへの組織の許可も必要です。

```powershell
git clone https://github.com/Yoshiaki-Ida/Items.git
git clone https://github.com/Yoshiaki-Ida/shared-skills.git
Set-Location .\Items\redmine-ticket-correction
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .\config\config.example.json .\config\config.json
```

既存の設定がある場合はコピーせず、その内容を確認します。
設定とSkillの導入は、上記の各READMEを参照してください。

## 範囲と検証

Jira連携、品質分析、音声の文字起こしは含めません。
議事録生成スクリプト、dry-run、模擬APIでの登録と再取得、Windows用BAT、Skill配備をテストします。
実Redmineへの登録と、Copilotによる実会議の抽出精度は導入先で確認してください。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

このコマンドは `redmine-ticket-correction` 内で実行します。
APIキー、社内URL、実会議の入力・出力はコミットしないでください。