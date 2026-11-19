from __future__ import annotations

import zipfile
from xml.etree import ElementTree

import pytest
from lxml import etree

from manual_tool.converter import (
    WORD_NS,
    _annotate_risky_word_graphics,
    _parse_word_document,
    _promote_textbox_content,
    _serialize_word_document,
    document_to_markdown,
)
from manual_tool.renderer import render_document

MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
ARTO = "http://schemas.microsoft.com/office/word/2006/arto"


def write_docx(path, document_xml):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
          <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
          <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
        </Types>""")
        archive.writestr("_rels/.rels", """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
        </Relationships>""")
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        archive.writestr("word/media/untouched.bin", b"unchanged graphic data")


@pytest.mark.parametrize("declaration", ['xmlns:arto="' + ARTO + '"', "xmlns:arto='" + ARTO + "'"])
def test_scoped_namespace_round_trip_preserves_compatibility_values(declaration):
    xml = f"""<w:document xmlns:w="{WORD_NS}" xmlns:mc="{MC}" xmlns:arto="{ARTO}" mc:Ignorable="arto">
      <!-- keep this comment -->
      <w:body>
        <w:p {declaration} mc:Ignorable="arto"><w:r><w:t>First</w:t></w:r></w:p>
        <w:p {declaration}><w:r><w:t>Second</w:t></w:r></w:p>
        <w:p xmlns:arto="urn:local" mc:Ignorable="arto" mc:PreserveElements="arto:shape">
          <mc:AlternateContent><mc:Choice Requires="arto"><arto:shape/></mc:Choice></mc:AlternateContent>
        </w:p>
        <w:p xmlns="urn:default"><item/><item xmlns=""/></w:p>
      </w:body></w:document>""".encode()
    rewritten = _serialize_word_document(_parse_word_document(xml))
    ElementTree.fromstring(rewritten)  # Rejects duplicate xmlns attributes.
    root = etree.fromstring(rewritten)
    assert root.nsmap["arto"] == ARTO
    scoped = root.find(".//{" + WORD_NS + "}p[@{" + MC + "}PreserveElements]")
    assert scoped.nsmap["arto"] == "urn:local"
    assert scoped.get("{" + MC + "}Ignorable") == "arto"
    assert scoped.get("{" + MC + "}PreserveElements") == "arto:shape"
    assert scoped.find(".//{" + MC + "}Choice").get("Requires") == "arto"
    assert root.find(".//{urn:default}item") is not None
    assert root.find(".//item") is not None
    assert b"keep this comment" in rewritten
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        for prefix in node.get("{" + MC + "}Ignorable", "").split():
            assert prefix in node.nsmap


@pytest.mark.parametrize("graphics", [False, True])
def test_docx_conversion_preserves_tables_textboxes_and_other_parts(tmp_path, monkeypatch, graphics):
    textbox = """<w:p><w:r><w:pict><v:shape id="shape1" style="width:100pt;height:20pt">
      <v:textbox><w:txbxContent><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Textbox label</w:t></w:r></w:p></w:txbxContent></v:textbox>
      </v:shape></w:pict><w:drawing><wpg:wgp/></w:drawing></w:r></w:p>""" if graphics else ""
    xml = f"""<w:document xmlns:w="{WORD_NS}" xmlns:mc="{MC}" xmlns:arto="{ARTO}"
      xmlns:v="urn:schemas-microsoft-com:vml"
      xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" mc:Ignorable="arto">
      <w:body><w:p xmlns:arto="{ARTO}"><w:r><w:t>Ordinary paragraph</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:p xmlns:arto="{ARTO}"><w:r><w:t>Table cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      {textbox}</w:body></w:document>""".encode()
    if not graphics:
        xml = xml.replace(f'<w:p xmlns:arto="{ARTO}">'.encode(), b"<w:p>")
    source = tmp_path / "source.docx"
    write_docx(source, xml)
    original_bytes = source.read_bytes()
    annotated, warnings = _annotate_risky_word_graphics(source, tmp_path / "prepared")
    promoted = _promote_textbox_content(annotated, tmp_path / "prepared")
    with zipfile.ZipFile(promoted) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
        assert root.find(".//{" + WORD_NS + "}tbl") is not None
        assert archive.read("word/media/untouched.bin") == b"unchanged graphic data"
        if graphics:
            shape = root.find(".//{urn:schemas-microsoft-com:vml}shape")
            assert shape.attrib == {"id": "shape1", "style": "width:100pt;height:20pt"}
            assert len(warnings) == 1

    # Exercise the real Mammoth fallback and the normal Markdown -> HTML path.
    monkeypatch.setattr("manual_tool.converter.shutil.which", lambda name: None)
    output = tmp_path / "converted"
    output.mkdir()
    markdown = document_to_markdown(source, output)
    html = render_document(markdown)
    assert "Ordinary paragraph" in html
    assert "<table>" in html and "Table cell" in html
    if graphics:
        assert markdown.count("Textbox label") == 1
        assert "変換上の注意" in markdown
    assert source.read_bytes() == original_bytes
    assert not (output / "word-conversion.docx").exists()
    assert not (output / "word-graphics-warnings.docx").exists()
    assert not list(tmp_path.rglob("debug_document.xml"))
    assert not list(tmp_path.rglob("debug_xml_error.txt"))


def test_invalid_xml_logs_coordinates_without_document_text(tmp_path, caplog, monkeypatch):
    monkeypatch.chdir(tmp_path)
    secret = "CONFIDENTIAL_DOCUMENT_TEXT"
    with pytest.raises(ValueError, match="line 1, column") as error:
        _parse_word_document(f'<w:document xmlns:w="urn:w"><{secret}></w:document>'.encode())
    assert "Word XML parsing failed" in caplog.text
    assert secret not in caplog.text
    assert secret not in str(error.value)
    assert not list(tmp_path.iterdir())


def test_promoted_textbox_preserves_shadowed_prefix_aliases(tmp_path):
    source = tmp_path / "aliases.docx"
    xml = f"""<w:document xmlns:w="{WORD_NS}" xmlns:mc="{MC}" xmlns:arto="{ARTO}"
        xmlns:other="urn:local" xmlns:v="urn:schemas-microsoft-com:vml">
      <w:body><w:p><w:r><w:pict><v:shape xmlns:arto="urn:local">
        <v:textbox><w:txbxContent><w:p mc:Ignorable="arto" mc:PreserveElements="arto:shape">
          <w:r><w:t>Scoped label</w:t></w:r>
          <mc:AlternateContent><mc:Choice Requires="arto"><arto:shape/></mc:Choice></mc:AlternateContent>
        </w:p></w:txbxContent></v:textbox>
      </v:shape></w:pict></w:r></w:p></w:body></w:document>""".encode()
    write_docx(source, xml)
    prepared = _promote_textbox_content(source, tmp_path / "prepared")
    with zipfile.ZipFile(prepared) as archive:
        rewritten = archive.read("word/document.xml")
    ElementTree.fromstring(rewritten)
    root = etree.fromstring(rewritten)
    promoted = root.find("./{" + WORD_NS + "}body/{" + WORD_NS + "}p[@{" + MC + "}Ignorable]")
    assert promoted is not None
    assert promoted.nsmap["arto"] == "urn:local"
    assert promoted.get("{" + MC + "}PreserveElements") == "arto:shape"
    assert promoted.find(".//{" + MC + "}Choice").get("Requires") == "arto"
    assert promoted.find(".//{urn:local}shape") is not None
    assert root.nsmap["arto"] == ARTO
