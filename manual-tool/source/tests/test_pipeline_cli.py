from __future__ import annotations

from manual_tool.cli import main
from manual_tool.pipeline import process_document


VALID = """# 概要

# 機能仕様

## 入力

説明

## 出力

説明

## 異常時動作

説明

# 注意事項

説明
"""


def test_pipeline_accepts_html(tmp_path):
    source = tmp_path / "manual.html"
    source.write_text("<h1>概要</h1><p>HTML入力</p>", encoding="utf-8")

    result = process_document(source)

    assert result.markdown_path.exists()
    assert result.fixed_markdown_path.exists()
    assert result.html_path.exists()
    assert result.report_path.exists()


def test_cli_processes_multiple_files_into_separate_directories(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.html"
    first.write_text(VALID, encoding="utf-8")
    second.write_text("<h1>概要</h1><p>second</p>", encoding="utf-8")
    output = tmp_path / "out"

    exit_code = main([str(first), str(second), "--output-dir", str(output)])

    assert exit_code == 0
    assert (output / "first_manual" / "first.html").exists()
    assert (output / "second_manual" / "second.md").exists()
    assert (output / "second_manual" / "second.html").exists()


def test_cli_continues_after_invalid_input(tmp_path):
    valid = tmp_path / "valid.md"
    valid.write_text(VALID, encoding="utf-8")
    missing = tmp_path / "missing.md"

    exit_code = main([str(missing), str(valid)])

    assert exit_code == 2
    assert (tmp_path / "valid_manual" / "valid.html").exists()
