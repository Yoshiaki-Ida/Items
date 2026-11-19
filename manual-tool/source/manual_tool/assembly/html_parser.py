from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from bs4 import BeautifulSoup, Tag


HEADING_NUMBER = re.compile(
    r"^\s*[0-9０-９]+(?:[.．][0-9０-９]+)*(?:[.．][ \t]*|[ \t]+)(?P<title>\S.*)$"
)


def strip_heading_number(title: str) -> str:
    match = HEADING_NUMBER.match(title)
    return match.group("title").strip() if match else title.strip()


@dataclass
class HtmlPart:
    path: Path
    title: str
    soup: BeautifulSoup
    headings: list[Tag]


def read_html(path: Path) -> HtmlPart:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("HTMLはUTF-8で保存してください。") from exc
    if not text.strip():
        raise ValueError("HTMLが空です。")
    try:
        soup = BeautifulSoup(text, "html.parser")
    except Exception as exc:
        raise ValueError(f"HTMLを解析できません: {exc}") from exc
    headings = list(soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]))
    first_h1 = next((heading for heading in headings if heading.name == "h1"), None)
    title = first_h1.get_text(" ", strip=True) if first_h1 else ""
    return HtmlPart(path=path, title=title, soup=soup, headings=headings)


def heading_level(heading: Tag) -> int:
    return int(heading.name[1])


def body_nodes(part: HtmlPart) -> list:
    container = part.soup.body or part.soup
    return list(container.contents)
