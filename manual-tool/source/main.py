from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in {"batch", "build", "web"}:
        print("Usage: python main.py batch <files...> | python main.py build <manual.yaml> | python main.py web", file=sys.stderr)
        return 2
    mode, *remaining = arguments
    if mode == "batch":
        from manual_tool.cli import main as cli_main

        return cli_main(remaining)
    if mode == "build":
        from manual_tool.assembly.cli import main as build_main

        return build_main(remaining)

    import uvicorn

    uvicorn.run("manual_tool.app:app", host="127.0.0.1", port=8765, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
