# ManualTool アーキテクチャ

## 方針

ManualToolは、バッチ変換とブラウザ編集で同じ変換・Lint・HTML生成処理を使用します。

```text
manual-convert.bat -> CLI   -> pipeline -> converter / lint_engine / renderer
manual-edit.bat    -> Web API ---------> converter / lint_engine / renderer
build.bat          -> CLI   -> assembly/schema / validator / builder / html_parser
manual-edit.bat    -> Web API ---------> assembly/schema / validator / builder / html_parser
```

## 既存プロジェクトの扱い

次のプロジェクトはManualToolの移行元であり、互換確認用の参照専用プロジェクトとして扱います。

- `projects/experiments/CreateManual`
- `projects/experiments/EditManual`

新機能と不具合修正はManualToolへ実装し、上記2プロジェクトには反映しません。

## 起動モード

- バッチモード: 複数文書の変換、Lint、自動修正、成果物出力、終了コード判定
- Webモード: フォルダ内文書のオープン、文書切り替え、編集、個別修正、プレビュー、ダウンロード
- フォルダモード: ユーザーがダイアログで許可したフォルダだけをワークスペース化し、文書ツリーから選択して別フォルダへ書き出す
- マニュアル編集モード: 個別HTMLの構成をGUIで編集し、章番号を持たないYAMLへ保存
- マニュアル構築モード: GUIまたはCLIから同じ決定論的Builderを呼び出し、統合HTMLを生成

## 共通入力形式

- `.docx`
- `.md`, `.markdown`（UTF-8）
- `.html`, `.htm`（UTF-8）

HTMLの表はraw HTMLとしてMarkdown内に保持します。バッチ入力したHTMLから参照される同一フォルダ配下のローカル画像は、成果物の`images`フォルダへコピーします。

Word変換では、複合図や埋め込みオブジェクトを含む段落をXML上で検出し、変換専用DOCXの該当位置へ注意マーカーを追加します。画像と埋め込みVisioは元データおよび既存プレビューを使う通常経路で変換し、注意マーカーはHTML変換後に原本確認を促す引用表示へ置換します。Word COMによる完成図全体の再描画や派生VSDX生成は行いません。Visio COMを利用できない場合や画像変換に失敗した場合は、元DOCX内の表示用画像を使用します。

WordからHTMLへ変換した直後に、段落書式由来の`blockquote`を表内・表外とも解除し、子要素と文字列は維持します。変換上の注意はこの正規化後に専用の引用ブロックとして追加するため除去されません。HTMLファイルや編集済みHTMLに明示された引用は、このWord専用の正規化対象にしません。

ワークスペース内のパスはバックエンドで正規化し、選択したルート外を指す相対パスやシンボリックリンクを拒否します。編集結果はセッションへ保存し、原本へは書き戻しません。

ブラウザ内の編集プレビューと構成元HTMLプレビューは、`sandbox`付きiframeへ表示し、入力文書に含まれるJavaScriptやフォームを実行しません。ダウンロード用HTMLの生成内容とは信頼境界を分離します。

個別ファイルの編集ビューは、スクリプト実行を許可しない`sandbox="allow-same-origin"`の専用iframeを使用します。親画面がレンダリング済み`article`内の許可要素を選択し、見出し番号を除いたテキスト、本文・リスト項目・表セル等の文字列、許可範囲内のフォントサイズと太字、画像参照、文字列行・画像・表の限定的な構造だけを変更します。入れ子のリスト項目は子リストを維持したまま、その項目自身の文字列だけを編集します。文字列行の前後挿入とブロック削除、画像の追加・削除、表の挿入、非結合表の行列追加・削除はDOM操作として実行し、最後の行または列の削除は表全体の削除として扱います。選択セルで指定したpt単位の横幅は同じ物理列、縦幅は同じ物理行へ展開し、後から追加した行列には隣接元の寸法を引き継ぎます。結合セルを含む表では対象列を一意に判断できないため、構造・寸法操作をUIで無効にします。

元データはスクロール比率、通常プレビューと編集ビューは`article`直下相当のブロック索引を共有し、3ビューの表示位置を同期します。通常プレビュー上の編集可能要素は同じ序数の編集要素へ対応付け、クリック時に編集ビューを開いて選択します。行番号付きLint指摘は元データの該当行を選択し、共有スクロール比率を各HTMLビューにも反映します。

保存APIは`article`本文を再検証し、script、フォーム、イベント属性、編集用属性を除去してからhybrid Markdownへ戻します。style属性は原則除去し、`manual-text-row`の`#RRGGBB`背景色、`manual-text-row`と`p.manual-underlined-block`の1ptまたは3ptの単線下線、`manual-font-size`の6～72pt、`manual-bold`の固定`font-weight:700`、表セルの`#RRGGBB`または透明の背景色と6～720ptの幅・高さだけを正規化して再構築します。専用ブロック、フォントマーカー、下線付き通常本文、表はhybrid Markdown内でHTMLとして保持するため、再編集、通常プレビュー、HTML出力、Builder構築後も体裁が維持されます。セッション、Lint、通常プレビュー、HTML出力は既存経路を共有し、`manual_tool/assembly`、YAML Schema、自動採番処理には依存しません。

編集セッションは`%TEMP%/manual-tool`配下のUUIDディレクトリへ保存します。書き出し完了時と変換失敗時に即時削除し、起動時には24時間を超えたUUIDセッションディレクトリを削除します。UUID形式でない同階層のディレクトリは削除対象にしません。

`manual_tool/assembly`はGUIとFastAPIへ依存しません。YAML Schema、HTML解析、検証、採番、目次、参照調整、構築処理を提供し、CIや別ツールから直接利用できます。
