# ManualTool Windows版

ManualToolは、Word・Markdown・HTMLの原稿を整えて、ブラウザで読めるマニュアルを作るWindowsツールです。PC上で原稿の変換・編集・チェックやPlantUMLの図の表示ができ、複数のHTMLを目次付きのマニュアルにまとめられます。

## 入手・起動

Git for Windowsを入れ、保存先でPowerShellを開きます。

```powershell
git clone --branch main --depth 1 --filter=blob:none --sparse https://github.com/Yoshiaki-Ida/Items.git Items
git -C .\Items sparse-checkout set manual-tool
Set-Location .\Items\manual-tool
```

`ManualTool.bat` をダブルクリックしてください。ブラウザで `http://127.0.0.1:8765/` が開きます。

終了するときは、起動した黒いコンソール画面を閉じてください。

## PlantUML

初回だけ、配布フォルダのPowerShellで次を実行してJavaを取得します。

```powershell
powershell.exe -NoProfile -File .\Setup-PlantUML.ps1
```

セットアップ後、ManualToolを起動すると配置したJavaと同梱のPlantUMLが使用されます。
Markdownを開くと図がプレビューに表示され、書き出したHTMLにはSVGとPlantUML原文が保存されます。
ManualToolの起動中は、書き出したHTMLの「PlantUMLソース」を編集すると図が自動で更新されます。
印刷・PDF出力には図が表示されます。
## 指摘一覧の出力

個別ファイル編集の「指摘」欄で「Markdown出力」を押すと `lint-report.md` を取得できます。
HTMLのフォルダ書き出し時も補助フォルダに生成されます。

## 注意

- Windows向けの配布物です。
- 変換・編集対象のファイルは利用者が選択したフォルダから読み込みます。
- Wordの数式変換にはPandocが必要です。未導入時は通常のWord変換へフォールバックします。
- 埋め込みVisioやEMF/WMFのPNG変換には、環境に応じてPowerShellやMicrosoft Visioが必要です。
- Windows Defenderや組織のポリシーで未知のEXEがブロックされる場合があります。
- 取得したフォルダの構成を保ったまま使用してください。
- 詳細な操作手順は `docs/USER_GUIDE.html` を開いて確認してください。
