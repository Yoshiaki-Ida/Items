from __future__ import annotations

import json
from pathlib import Path

from .converter import document_to_markdown
from .lint_engine import apply_all_fixes, lint_text, load_rules
from .models import ProcessResult
from .renderer import render_document


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def process_document(
    source: Path,
    output_dir: Path | None = None,
    rules_path: Path | None = None,
    *,
    auto_fix: bool = True,
) -> ProcessResult:
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"入力ファイルがありません: {source}")
    output_dir = (output_dir or source.parent / f"{source.stem}_manual").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rules = load_rules((rules_path or PROJECT_ROOT / "config" / "rules.yaml").resolve())
    markdown_text = document_to_markdown(source, output_dir)
    original_issues = lint_text(markdown_text, rules)
    fixed_text, applied = apply_all_fixes(markdown_text, rules) if auto_fix else (markdown_text, [])
    issues = original_issues + applied

    markdown_path = source if source.suffix.lower() in {".md", ".markdown"} else output_dir / f"{source.stem}.md"
    if markdown_path != source:
        markdown_path.write_text(markdown_text, encoding="utf-8")
    fixed_path = output_dir / f"{source.stem}_fixed.md"
    fixed_path.write_text(fixed_text, encoding="utf-8")
    html_path = output_dir / f"{source.stem}.html"
    html_path.write_text(
        render_document(fixed_text, source.stem, image_dir=output_dir / "images"),
        encoding="utf-8",
    )
    report_path = output_dir / "lint-report.json"
    report_path.write_text(
        json.dumps([issue.to_dict() for issue in issues], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ProcessResult(source, output_dir, markdown_path, fixed_path, html_path, report_path, tuple(issues))
