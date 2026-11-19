from __future__ import annotations

from bs4 import BeautifulSoup

from manual_tool.renderer import normalize_markdown_table_blocks, render_document


def test_compact_markdown_table_after_prose_is_rendered_as_html_table():
    markdown = "# 概要\n\n本文です。\n| 名称 | 型名 |\n|---|---|\n| 製品 | ABC |\n"

    soup = BeautifulSoup(render_document(markdown), "html.parser")

    assert soup.find("table") is not None
    assert [cell.get_text(strip=True) for cell in soup.select("th")] == ["名称", "型名"]
    assert [cell.get_text(strip=True) for cell in soup.select("td")] == ["製品", "ABC"]
    assert soup.find("p").get_text(strip=True) == "本文です。"
    assert soup.select_one("style[data-manual-tool-document-style]") is not None


def test_table_normalization_does_not_change_pipe_table_inside_code_fence():
    markdown = "```markdown\n本文\n| A | B |\n|---|---|\n| 1 | 2 |\n```\n"

    assert normalize_markdown_table_blocks(markdown) == markdown


def test_mathml_is_preserved_in_rendered_html():
    markdown = '# 数式\n\n<math xmlns="http://www.w3.org/1998/Math/MathML"><msup><mi>x</mi><mn>2</mn></msup></math>\n'

    soup = BeautifulSoup(render_document(markdown), "html.parser")

    assert soup.find("math") is not None
    assert soup.find("msup") is not None
    assert soup.find("mi").get_text() == "x"
