from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import process_document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="マニュアルを一括変換・体裁チェックします。")
    parser.add_argument("inputs", nargs="+", type=Path, help=".docx/.md/.markdown/.html/.htmファイル")
    parser.add_argument("-o", "--output-dir", type=Path, help="成果物の出力先。複数入力時は配下に入力別フォルダを作成")
    parser.add_argument("--rules", type=Path, help="Lintルールファイル")
    parser.add_argument("--no-auto-fix", action="store_true", help="用語統一などの自動修正を行わない")
    parser.add_argument("--fail-on-error", action="store_true", help="Lint ERRORがあれば終了コード1を返す")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    failed = False
    has_lint_error = False
    multiple = len(args.inputs) > 1
    for source in args.inputs:
        destination = None
        if args.output_dir:
            destination = args.output_dir / f"{source.stem}_manual" if multiple else args.output_dir
        try:
            result = process_document(
                source,
                destination,
                args.rules,
                auto_fix=not args.no_auto_fix,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"ERROR [{source}]: {exc}", file=sys.stderr)
            failed = True
            continue
        has_lint_error = has_lint_error or result.error_count > 0
        print(f"完了: {result.source_path}")
        print(f"  出力: {result.output_dir}")
        print(f"  ERROR={result.error_count}, WARNING={result.warning_count}")
    if failed:
        return 2
    return 1 if args.fail_on_error and has_lint_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
