from __future__ import annotations

import base64
import mimetypes
import re
from html import escape, unescape
from pathlib import Path

from .plantuml import PlantUmlError, render_svg_uri


LEGACY_DOCUMENT_STYLE = """
body{margin:0;color:#243447;font-family:'Yu Gothic UI',Meiryo,sans-serif;line-height:1.75}
article{max-width:980px;margin:auto;padding:32px 48px}h1,h2,h3{line-height:1.35;color:#17365d;border-bottom:1px solid #d9e2ec;padding-bottom:.25em}
table{width:100%;border-collapse:collapse;margin:1em 0;display:block;overflow:auto}th,td{border:1px solid #9fb3c8;padding:8px;vertical-align:top}th{background:#eaf2f8}.manual-table-points{display:table;width:auto;table-layout:fixed}
img{max-width:100%;height:auto}pre{overflow:auto;background:#17202a;color:#f4f6f7;padding:16px;border-radius:6px}blockquote{border-left:4px solid #2684ff;padding-left:16px;color:#52667a}.manual-text-row{margin:1em 0;padding:8px 10px}.manual-text-row>p{margin:0}
"""

STYLE = """
body{margin:0;color:#243447;font-family:'Yu Gothic UI',Meiryo,sans-serif;line-height:1.75}
article{max-width:980px;margin:auto;padding:32px 48px}h1,h2,h3{line-height:1.35;color:#17365d;border-bottom:1px solid #d9e2ec;padding-bottom:.25em}
table{width:100%;border-collapse:collapse;margin:1em 0;display:block;overflow:auto}th,td{border:1px solid #9fb3c8;padding:8px;vertical-align:top}th{background:#eaf2f8}.manual-table-points{display:table;width:auto;table-layout:fixed}
img{max-width:100%;height:auto}pre{overflow:auto;background:#17202a;color:#f4f6f7;padding:16px;border-radius:6px}blockquote{margin:1em 0;padding:12px 16px;border-left:4px solid #2684ff;border-radius:0 5px 5px 0;background:#eef6ff;color:#52667a}.manual-text-row{margin:1em 0;padding:8px 10px}.manual-text-row>p{margin:0}
"""

TABLE_SEPARATOR = re.compile(
    r"^ {0,3}\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
FENCE = re.compile(r"^ {0,3}(?P<marks>`{3,}|~{3,})(?:[^`~]*)$")
PLANTUML_BLOCK = re.compile(
    r'<pre><code class="language-plantuml">(?P<source>.*?)</code></pre>', re.I | re.S
)
PLANTUML_STYLE = """
.plantuml-diagram{margin:1em 0}
.plantuml-editor textarea{display:block;box-sizing:border-box;width:100%;min-height:9em;font-family:monospace}
.plantuml-toolbar{margin:.6em 0}
.plantuml-status{display:block}
@media print{
  .plantuml-editor,.plantuml-toolbar,.plantuml-status{display:none!important}
  .plantuml-diagram{break-inside:avoid}
}
"""
PLANTUML_SCRIPT = Path(__file__).resolve().parent.parent / "static" / "plantuml-document.js"


def _plantuml_figure(match: re.Match[str]) -> str:
    source = unescape(match.group("source"))
    image = '<img alt="PlantUMLの図" hidden>'
    status = ""
    try:
        uri = render_svg_uri(source)
        image = f'<img alt="PlantUMLの図" src="{uri}">'
    except PlantUmlError as exc:
        status = str(exc)
    return (
        f'<figure class="plantuml-diagram" data-plantuml-diagram>{image}'
        '<details class="plantuml-editor"><summary>PlantUMLソース</summary><p>この欄の内容は印刷・PDF出力に含まれません。</p>'
        f'<textarea aria-label="PlantUMLソース" spellcheck="false">\n{escape(source)}</textarea>'
        '<button type="button">再試行</button>'
        '</details>'
        f'<output class="plantuml-status" aria-live="polite">{escape(status)}</output></figure>'
    )


def normalize_markdown_table_blocks(markdown_text: str) -> str:
    """Separate compact pipe tables from adjacent prose for Markdown rendering."""
    lines = markdown_text.splitlines()
    if len(lines) < 2:
        return markdown_text

    in_fence: list[bool] = []
    fence_character: str | None = None
    fence_length = 0
    for line in lines:
        fence = FENCE.match(line)
        if fence:
            marks = fence.group("marks")
            if fence_character is None:
                fence_character = marks[0]
                fence_length = len(marks)
                in_fence.append(True)
                continue
            if marks[0] == fence_character and len(marks) >= fence_length:
                in_fence.append(True)
                fence_character = None
                fence_length = 0
                continue
        in_fence.append(fence_character is not None)

    blank_before: set[int] = set()
    blank_after: set[int] = set()
    for index in range(1, len(lines)):
        if in_fence[index] or in_fence[index - 1] or not TABLE_SEPARATOR.match(lines[index]):
            continue
        if "|" not in lines[index - 1] or not lines[index - 1].strip():
            continue
        table_end = index + 1
        while table_end < len(lines) and not in_fence[table_end] and "|" in lines[table_end] and lines[table_end].strip():
            table_end += 1
        if index > 1 and lines[index - 2].strip():
            blank_before.add(index - 1)
        if table_end < len(lines) and lines[table_end].strip():
            blank_after.add(table_end - 1)

    normalized: list[str] = []
    for index, line in enumerate(lines):
        if index in blank_before and normalized and normalized[-1] != "":
            normalized.append("")
        normalized.append(line)
        if index in blank_after:
            normalized.append("")
    ending = "\n" if markdown_text.endswith(("\n", "\r")) else ""
    return "\n".join(normalized) + ending


def _resolve_images(body: str, image_base: str | None, image_dir: Path | None) -> str:
    pattern = re.compile(r'(?P<prefix>src=["\'])images/(?P<path>[^"\']+)(?P<suffix>["\'])')

    def replace(match: re.Match) -> str:
        relative = match.group("path").replace("\\", "/")
        if image_base:
            return f'{match.group("prefix")}{image_base.rstrip("/")}/{relative}{match.group("suffix")}'
        if image_dir:
            target = (image_dir / relative).resolve()
            try:
                target.relative_to(image_dir.resolve())
            except ValueError:
                return match.group(0)
            if target.is_file():
                mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                encoded = base64.b64encode(target.read_bytes()).decode("ascii")
                return f'{match.group("prefix")}data:{mime};base64,{encoded}{match.group("suffix")}'
        return match.group(0)

    return pattern.sub(replace, body)


def render_document(
    markdown_text: str,
    title: str = "Manual Preview",
    *,
    image_base: str | None = None,
    image_dir: Path | None = None,
) -> str:
    import markdown

    body = markdown.markdown(
        normalize_markdown_table_blocks(markdown_text),
        extensions=["extra", "admonition", "sane_lists", "toc"],
    )
    body = _resolve_images(body, image_base, image_dir)
    style = STYLE
    script = ""
    if PLANTUML_BLOCK.search(body):
        body = PLANTUML_BLOCK.sub(_plantuml_figure, body)
        style += PLANTUML_STYLE
        body += '<div class="plantuml-toolbar"><button type="button" data-plantuml-save disabled>HTMLを保存</button></div>'
        script = f'<script data-plantuml-script>{PLANTUML_SCRIPT.read_text(encoding="utf-8")}</script>'
    return f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{escape(title)}</title><style data-manual-tool-document-style>{style}</style></head><body><article>{body}</article>{script}</body></html>'
