from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import ManualValidationError, build_manual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="manual.yamlから完成版マニュアルHTMLを構築します。")
    parser.add_argument("yaml", type=Path, help="manual.yamlのパス")
    args = parser.parse_args(argv)
    try:
        result = build_manual(args.yaml)
    except (OSError, ValueError, ManualValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"構築完了: {result.output_path}")
    print(f"見出し: {len(result.headings)}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
