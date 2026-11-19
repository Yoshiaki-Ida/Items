from __future__ import annotations

import zipfile
from types import SimpleNamespace

from manual_tool.converter import (
    _annotate_risky_word_graphics,
    _extract_embedded_visio,
    _normalize_extracted_image_sources,
    _promote_textbox_content,
    _replace_graphic_warning_markers,
    _replace_visio_previews,
    _unwrap_word_blockquotes,
    _word_to_markdown,
    document_to_markdown,
    html_to_hybrid_markdown,
    normalize_document_headings,
    normalize_heading_levels,
)


def test_risky_word_graphics_are_annotated_but_ordinary_images_are_not(tmp_path):
    source = tmp_path / "manual.docx"
    document_xml = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
      xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
      xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
      xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" mc:Ignorable="w15">
      <w:body>
        <w:p><w:r><w:drawing><wpg:wgp/></w:drawing></w:r></w:p>
        <w:p><w:r><w:drawing/></w:r></w:p>
        <w:p><w:r><w:object><w:txbxContent><w:p><w:r><w:drawing><wpg:wgp/></w:drawing></w:r>
        </w:p></w:txbxContent></w:object></w:r></w:p>
      </w:body></w:document>'''
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    annotated, warnings = _annotate_risky_word_graphics(source, tmp_path / "session")

    assert annotated != source
    with zipfile.ZipFile(annotated) as archive:
        rewritten = archive.read("word/document.xml").decode("utf-8")
    assert len(warnings) == 2
    assert rewritten.count("MANUALTOOLGRAPHICWARNING0001TOKEN") == 1
    assert rewritten.count("MANUALTOOLGRAPHICWARNING0002TOKEN") == 1
    assert "MANUALTOOLGRAPHICWARNING0003TOKEN" not in rewritten
    assert 'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"' in rewritten


def test_graphic_warning_marker_is_replaced_with_note():
    html = "<p>MANUALTOOLGRAPHICWARNING0002TOKEN</p>"

    replaced = _replace_graphic_warning_markers(
        html,
        {"MANUALTOOLGRAPHICWARNING0002TOKEN": "変換上の注意: 元のWord文書を確認してください。"},
    )

    assert "MANUALTOOLGRAPHICWARNING0002TOKEN" not in replaced
    assert "<blockquote>" in replaced
    assert "変換上の注意" in replaced


def test_html_conversion_preserves_tables():
    markdown = html_to_hybrid_markdown(
        "<h1>概要</h1><p>説明です。</p><table><tr><th>A</th></tr><tr><td>B</td></tr></table>"
    )
    assert "# 概要" in markdown
    assert "<table>" in markdown
    assert "<td>B</td>" in markdown


def test_html_conversion_preserves_mathml():
    mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mfrac><mi>a</mi><mi>b</mi></mfrac></math>'

    markdown = html_to_hybrid_markdown(f"<p>式：</p>{mathml}")

    assert "<math" in markdown
    assert "<mfrac>" in markdown
    assert "<mi>a</mi>" in markdown


def test_html_conversion_preserves_admonition_blocks():
    html = '<div class="admonition warning"><p class="admonition-title">Warning</p><p>危険です。</p></div>'

    markdown = html_to_hybrid_markdown(html)

    assert '<div class="admonition warning">' in markdown
    assert '<p class="admonition-title">Warning</p>' in markdown
    assert "危険です。" in markdown


def test_word_blockquote_cleanup_unwraps_normal_paragraphs_and_table_cells():
    html = """
      <blockquote><p>表外の引用</p></blockquote>
      <table><thead><tr><th><blockquote><p><strong>品名</strong></p></blockquote></th></tr></thead>
      <tbody><tr><td><blockquote><p><a href="#detail">説明</a></p></blockquote></td></tr></tbody></table>
    """

    cleaned = _unwrap_word_blockquotes(html)

    assert "<blockquote>" not in cleaned
    assert "<p>表外の引用</p>" in cleaned
    assert "<th><p><strong>品名</strong></p></th>" in cleaned
    assert '<td><p><a href="#detail">説明</a></p></td>' in cleaned


def test_html_conversion_keeps_semantic_blockquotes():
    markdown = html_to_hybrid_markdown("<blockquote><p>明示的な引用</p></blockquote>")

    assert markdown.startswith("> 明示的な引用")


def test_word_conversion_requests_mathml_from_pandoc(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr("manual_tool.converter._annotate_risky_word_graphics", lambda source, _output: (source, {}))
    monkeypatch.setattr("manual_tool.converter._extract_embedded_visio", lambda *_args: {})
    monkeypatch.setattr("manual_tool.converter.shutil.which", lambda _name: "pandoc")

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout='<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>')

    monkeypatch.setattr("manual_tool.converter.subprocess.run", run)
    markdown = _word_to_markdown(tmp_path / "manual.docx", tmp_path / "session")

    assert "--mathml" in commands[0]
    assert "<math" in markdown


def test_html_file_copies_relative_images(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "figure.png").write_bytes(b"png")
    source = source_dir / "manual.html"
    source.write_text('<h1>概要</h1><img src="figure.png">', encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()

    markdown = document_to_markdown(source, output)

    assert "images/figure.png" in markdown
    assert (output / "images" / "figure.png").read_bytes() == b"png"


def test_pandoc_absolute_image_paths_are_made_session_relative(tmp_path):
    image_dir = tmp_path / "session" / "images"
    media_dir = image_dir / "media"
    media_dir.mkdir(parents=True)
    image = media_dir / "image1.png"
    image.write_bytes(b"png")

    normalized = _normalize_extracted_image_sources(f'<img src="{image}">', image_dir)

    assert 'src="images/media/image1.png"' in normalized


def test_embedded_visio_is_extracted_converted_and_mapped(tmp_path, monkeypatch):
    source = tmp_path / "manual.docx"
    document_xml = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
      xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:v="urn:schemas-microsoft-com:vml">
      <w:body><w:object><v:shape><v:imagedata r:id="rPreview"/></v:shape>
      <o:OLEObject ProgID="Visio.Drawing.15" r:id="rVisio"/></w:object></w:body></w:document>'''
    relationships_xml = b'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rPreview" Target="media/image1.emf"/>
      <Relationship Id="rVisio" Target="embeddings/drawing.vsdx"/>
      </Relationships>'''
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", relationships_xml)
        archive.writestr("word/media/image1.emf", b"preview")
        archive.writestr("word/media/image2.emf", b"standalone")
        archive.writestr("word/embeddings/drawing.vsdx", b"visio")

    def convert(command, **_kwargs):
        input_dir = command[command.index("-InputDirectory") + 1]
        output_dir = command[command.index("-OutputDirectory") + 1]
        from pathlib import Path
        for source_file in Path(input_dir).iterdir():
            Path(output_dir, f"{source_file.stem}.png").write_bytes(b"png")

    monkeypatch.setattr("manual_tool.converter.subprocess.run", convert)
    output = tmp_path / "session"
    assets = _extract_embedded_visio(source, output)

    assert (output / "visio" / "drawing.vsdx").read_bytes() == b"visio"
    assert (output / "images" / "visio" / "drawing.png").read_bytes() == b"png"
    assert assets["image1.emf"][1] == "images/visio/drawing.png"
    assert assets["image2.emf"][1] == "images/visio/image2.png"
    assert 'src="images/visio/drawing.png"' in _replace_visio_previews(
        '<img src="images/media/image1.emf">', assets
    )
    assert 'src="images/visio/image2.png"' in _replace_visio_previews(
        '<img src="images/media/image2.emf">', assets
    )


def test_textbox_text_is_promoted_once_next_to_its_image(tmp_path):
    source = tmp_path / "manual.docx"
    document_xml = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
      xmlns:v="urn:schemas-microsoft-com:vml"><w:body><w:p><w:r><w:drawing/></w:r>
      <w:r><w:object><v:textbox><w:txbxContent><w:p><w:r><w:rPr><w:b/></w:rPr>
      <w:t>Important label</w:t></w:r></w:p></w:txbxContent></v:textbox></w:object></w:r>
      <w:r><w:object><v:textbox><w:txbxContent><w:p><w:r><w:t>Important label</w:t></w:r></w:p>
      </w:txbxContent></v:textbox></w:object></w:r></w:p></w:body></w:document>'''
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    prepared = _promote_textbox_content(source, tmp_path / "session")

    with zipfile.ZipFile(prepared) as archive:
        rewritten = archive.read("word/document.xml").decode("utf-8")
    assert rewritten.count("Important label") == 1
    assert "<w:b" in rewritten


def test_heading_levels_start_at_h1_and_keep_relative_depth():
    markdown = "## 章\n\n### 節\n\n##### 深い見出し\n"

    normalized = normalize_heading_levels(markdown)

    assert normalized == "# 章\n\n## 節\n\n#### 深い見出し\n"


def test_heading_normalization_ignores_fenced_code_blocks():
    markdown = "### 章\n\n```markdown\n## コード例\n```\n\n#### 節\n"

    normalized = normalize_heading_levels(markdown)

    assert normalized == "# 章\n\n```markdown\n## コード例\n```\n\n## 節\n"


def test_html_conversion_promotes_the_highest_heading_to_h1():
    markdown = html_to_hybrid_markdown("<h2>章</h2><h3>節</h3>")

    assert normalize_heading_levels(markdown) == "# 章\n\n## 節\n"


def test_existing_heading_numbers_are_renumbered_from_one():
    markdown = "## 2. 章\n\n### 2.2. 節\n\n### 2.3. 次の節\n"

    normalized = normalize_document_headings(markdown)

    assert normalized == "# １． 章\n\n## １．１． 節\n\n## １．２． 次の節\n"


def test_fullwidth_and_mixed_heading_numbers_are_recognized():
    markdown = "## ２． 章\n\n### ２．２． 節\n\n### ２.３. 次の節\n"

    normalized = normalize_document_headings(markdown)

    assert normalized == "# １． 章\n\n## １．１． 節\n\n## １．２． 次の節\n"
