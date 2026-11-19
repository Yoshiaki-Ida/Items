from __future__ import annotations

import base64
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = PROJECT_ROOT / "docs"
SOURCE = DOCS_ROOT / "USER_GUIDE.html"
DESTINATION = DOCS_ROOT / "USER_GUIDE_EMBEDDED.html"
IMAGE_NAMES = (
    "元データ画面.png",
    "プレビュー画面.png",
    "編集ビュー画面.png",
    "マニュアル編集画面.png",
)


def main() -> None:
    html = SOURCE.read_text(encoding="utf-8")
    for image_name in IMAGE_NAMES:
        image_path = DOCS_ROOT / image_name
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        data_uri = f"data:image/png;base64,{encoded}"
        html = html.replace(f'"{image_name}"', f'"{data_uri}"')
    DESTINATION.write_text(html, encoding="utf-8")
    print(f"Created {DESTINATION}")


if __name__ == "__main__":
    main()