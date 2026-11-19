from __future__ import annotations

import re
import shutil
import subprocess
import hashlib
import logging
import posixpath
import zipfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.dom import minidom
from xml.etree import ElementTree

from lxml import etree


SUPPORTED_EXTENSIONS = {".docx", ".md", ".markdown", ".html", ".htm"}
ATX_HEADING = re.compile(r"^(?P<indent> {0,3})(?P<marks>#{1,6})(?P<space>[ \t]+)(?P<title>.*)$")
FENCE = re.compile(r"^ {0,3}(?P<marks>`{3,}|~{3,})(?:[^`~]*)$")
HEADING_NUMBER = re.compile(
    r"^(?P<number>[0-9０-９]+(?:[.．][0-9０-９]+)*)(?:(?P<dot>[.．])(?P<space_after_dot>[ \t]*)|(?P<space>[ \t]+))(?P<title>\S.*)$"
)
FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")
RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
OFFICE_NS = "urn:schemas-microsoft-com:office:office"
VML_NS = "urn:schemas-microsoft-com:vml"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _fullwidth_section_number(counters: list[int]) -> str:
    return "．".join(str(value).translate(FULLWIDTH_DIGITS) for value in counters)


def normalize_heading_levels(markdown_text: str) -> str:
    """Shift all ATX headings so the highest heading in a file becomes H1."""
    lines = markdown_text.splitlines(keepends=True)
    heading_rows: list[tuple[int, re.Match[str]]] = []
    fence_character: str | None = None
    fence_length = 0
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        fence = FENCE.match(content)
        if fence:
            marks = fence.group("marks")
            if fence_character is None:
                fence_character = marks[0]
                fence_length = len(marks)
            elif marks[0] == fence_character and len(marks) >= fence_length:
                fence_character = None
                fence_length = 0
            continue
        if fence_character is not None:
            continue
        heading = ATX_HEADING.match(content)
        if heading:
            heading_rows.append((index, heading))

    if not heading_rows:
        return markdown_text
    shift = min(len(match.group("marks")) for _, match in heading_rows) - 1
    if shift <= 0:
        return markdown_text
    for index, match in heading_rows:
        ending = lines[index][len(lines[index].rstrip("\r\n")) :]
        level = len(match.group("marks")) - shift
        lines[index] = (
            f'{match.group("indent")}{"#" * level}{match.group("space")}{match.group("title")}{ending}'
        )
    return "".join(lines)


def normalize_heading_numbering(markdown_text: str) -> str:
    """Renumber existing heading prefixes from 1 using the file-local hierarchy."""
    lines = markdown_text.splitlines(keepends=True)
    counters: list[int] = []
    fence_character: str | None = None
    fence_length = 0
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        fence = FENCE.match(content)
        if fence:
            marks = fence.group("marks")
            if fence_character is None:
                fence_character = marks[0]
                fence_length = len(marks)
            elif marks[0] == fence_character and len(marks) >= fence_length:
                fence_character = None
                fence_length = 0
            continue
        if fence_character is not None:
            continue
        heading = ATX_HEADING.match(content)
        if not heading:
            continue
        level = len(heading.group("marks"))
        while len(counters) < level:
            counters.append(0)
        counters = counters[:level]
        counters[-1] += 1
        numbered_title = HEADING_NUMBER.match(heading.group("title"))
        if not numbered_title:
            continue
        ending = lines[index][len(content) :]
        number = _fullwidth_section_number(counters)
        lines[index] = (
            f'{heading.group("indent")}{heading.group("marks")}{heading.group("space")}'
            f'{number}． {numbered_title.group("title")}{ending}'
        )
    return "".join(lines)


def normalize_document_headings(markdown_text: str) -> str:
    return normalize_heading_numbering(normalize_heading_levels(markdown_text))


def _unwrap_word_blockquotes(html: str) -> str:
    """Remove quote wrappers introduced by Word styles, preserving their contents."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for blockquote in list(soup.find_all("blockquote")):
        blockquote.unwrap()
    return str(soup)


def html_to_hybrid_markdown(html: str) -> str:
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    for control in soup.select(".plantuml-toolbar:has([data-plantuml-save]), script[data-plantuml-script]"):
        control.decompose()
    diagrams: dict[str, str] = {}
    for index, figure in enumerate(soup.select("figure[data-plantuml-diagram]")):
        textarea = figure.select_one("textarea")
        if textarea is None:
            continue
        source = textarea.get_text().removeprefix("\n")
        longest = max((len(run) for run in re.findall(r"`+", source)), default=0)
        fence = "`" * max(3, longest + 1)
        token = f"MANUALTOOLPLANTUML{index}TOKEN"
        ending = "" if source.endswith("\n") else "\n"
        diagrams[token] = f"{fence}plantuml\n{source}{ending}{fence}"
        figure.replace_with(token)
    font_sizes: dict[str, str] = {}
    for index, inline in enumerate(soup.select("span.manual-font-size, span.manual-bold")):
        token = f"MANUALTOOLFONTSIZE{index}TOKEN"
        font_sizes[token] = str(inline)
        inline.replace_with(token)
    underlined_blocks: dict[str, str] = {}
    for index, block in enumerate(soup.select("p.manual-underlined-block")):
        token = f"MANUALTOOLUNDERLINEDBLOCK{index}TOKEN"
        underlined_blocks[token] = str(block)
        block.replace_with(token)
    text_rows: dict[str, str] = {}
    for index, block in enumerate(soup.select("div.manual-text-row")):
        token = f"MANUALTOOLTEXTROW{index}TOKEN"
        text_rows[token] = str(block)
        block.replace_with(token)
    admonitions: dict[str, str] = {}
    for index, block in enumerate(soup.select("div.admonition")):
        token = f"MANUALTOOLADMONITION{index}TOKEN"
        admonitions[token] = str(block)
        block.replace_with(token)
    tables: dict[str, str] = {}
    for index, table in enumerate(soup.find_all("table")):
        token = f"MANUALTOOLTABLE{index}TOKEN"
        tables[token] = str(table)
        table.replace_with(token)
    maths: dict[str, str] = {}
    for index, math in enumerate(soup.find_all("math")):
        token = f"MANUALTOOLMATH{index}TOKEN"
        maths[token] = str(math)
        math.replace_with(token)
    result = markdownify(str(soup), heading_style="ATX", bullets="-")
    for token, block in underlined_blocks.items():
        result = result.replace(token, f"\n\n{block}\n\n")
    for token, block in text_rows.items():
        result = result.replace(token, f"\n\n{block}\n\n")
    for token, block in admonitions.items():
        result = result.replace(token, f"\n\n{block}\n\n")
    for token, table in tables.items():
        result = result.replace(token, f"\n\n{table}\n\n")
    for token, math in maths.items():
        result = result.replace(token, math)
    for token, inline in font_sizes.items():
        result = result.replace(token, inline)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    for token, diagram in diagrams.items():
        result = result.replace(token, f"\n\n{diagram}\n\n")
    return result.strip() + "\n"


def _prepare_html_assets(source: Path, output_dir: Path, html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    image_dir = output_dir / "images"
    copied_names: set[str] = set()
    for index, image in enumerate(soup.find_all("img"), 1):
        if image.find_parent("figure", attrs={"data-plantuml-diagram": True}):
            continue
        src = image.get("src")
        if not src:
            continue
        parsed = urlparse(src)
        if parsed.scheme or parsed.netloc or src.startswith(("//", "#")):
            continue
        candidate = (source.parent / unquote(parsed.path)).resolve()
        try:
            candidate.relative_to(source.parent.resolve())
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        image_dir.mkdir(parents=True, exist_ok=True)
        name = candidate.name
        if name in copied_names or (image_dir / name).exists():
            name = f"{candidate.stem}_{index}{candidate.suffix}"
        shutil.copy2(candidate, image_dir / name)
        copied_names.add(name)
        image["src"] = f"images/{name}"
    return str(soup)


def _normalize_extracted_image_sources(html: str, image_dir: Path) -> str:
    """Rewrite Pandoc's absolute extracted-media paths to session-relative paths."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    root = image_dir.resolve()
    for image in soup.find_all("img"):
        src = image.get("src")
        if not src or src.replace("\\", "/").startswith("images/"):
            continue
        try:
            target = Path(unquote(urlparse(src).path or src)).resolve()
            relative = target.relative_to(root)
        except (OSError, ValueError):
            continue
        image["src"] = f"images/{relative.as_posix()}"
    return str(soup)


def _docx_part(base_part: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def _extract_embedded_visio(source: Path, output_dir: Path) -> dict[str, tuple[str, str]]:
    """Extract Visio files and convert embedded drawings and metafiles to PNG in one batch."""
    if not zipfile.is_zipfile(source):
        return {}

    visio_dir = output_dir / "visio"
    rendered_dir = output_dir / "images" / "visio"
    conversion_dir = output_dir / "vector-conversion"
    candidates: list[tuple[str, str, str]] = []
    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        document_part = "word/document.xml"
        relationships_part = "word/_rels/document.xml.rels"
        if document_part not in names or relationships_part not in names:
            return {}
        document = ElementTree.fromstring(archive.read(document_part))
        relationships = ElementTree.fromstring(archive.read(relationships_part))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
        namespaces = {"r": RELATIONSHIP_NS, "o": OFFICE_NS, "v": VML_NS}

        for container in document.iter():
            if not container.tag.endswith("}object"):
                continue
            embedded = container.find(".//o:OLEObject", namespaces)
            preview = container.find(".//v:imagedata", namespaces)
            if embedded is None or preview is None or not embedded.attrib.get("ProgID", "").startswith("Visio."):
                continue
            embedded_id = embedded.attrib.get(f"{{{RELATIONSHIP_NS}}}id")
            preview_id = preview.attrib.get(f"{{{RELATIONSHIP_NS}}}id")
            if embedded_id not in targets or preview_id not in targets:
                continue
            embedded_part = _docx_part(document_part, targets[embedded_id])
            preview_part = _docx_part(document_part, targets[preview_id])
            if embedded_part not in names or preview_part not in names:
                continue
            suffix = Path(embedded_part).suffix.lower()
            if suffix not in {".vsd", ".vsdx"}:
                continue
            visio_dir.mkdir(parents=True, exist_ok=True)
            destination = visio_dir / Path(embedded_part).name
            destination.write_bytes(archive.read(embedded_part))
            conversion_dir.mkdir(parents=True, exist_ok=True)
            (conversion_dir / destination.name).write_bytes(archive.read(embedded_part))
            digest = hashlib.sha256(archive.read(preview_part)).hexdigest()
            candidates.append((Path(preview_part).name.casefold(), digest, destination.stem))

        mapped_previews = {item[0] for item in candidates}
        for media_part in sorted(names):
            if not media_part.startswith("word/media/") or Path(media_part).suffix.lower() not in {".emf", ".wmf"}:
                continue
            conversion_dir.mkdir(parents=True, exist_ok=True)
            media_name = Path(media_part).name
            content = archive.read(media_part)
            (conversion_dir / media_name).write_bytes(content)
            if media_name.casefold() not in mapped_previews:
                candidates.append((media_name.casefold(), hashlib.sha256(content).hexdigest(), Path(media_name).stem))

    if not conversion_dir.is_dir():
        return {}
    rendered_dir.mkdir(parents=True, exist_ok=True)
    converter = Path(__file__).resolve().parents[1] / "scripts" / "convert-vector-to-png.ps1"
    try:
        subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-ExecutionPolicy", "Bypass",
                "-File", str(converter), "-InputDirectory", str(conversion_dir), "-OutputDirectory", str(rendered_dir),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        shutil.rmtree(conversion_dir, ignore_errors=True)

    result: dict[str, tuple[str, str]] = {}
    for preview_name, digest, stem in candidates:
        rendered = rendered_dir / f"{stem}.png"
        if rendered.is_file() and rendered.stat().st_size:
            result[preview_name] = (digest, f"images/visio/{rendered.name}")
    return result


def _replace_visio_previews(html: str, assets: dict[str, tuple[str, str]]) -> str:
    if not assets:
        return html
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for image in soup.find_all("img"):
        src = image.get("src")
        if not src:
            continue
        replacement = assets.get(Path(urlparse(src).path.replace("\\", "/")).name.casefold())
        if replacement:
            image["src"] = replacement[1]
    return str(soup)


def _replace_converted_metafiles(html: str, image_dir: Path) -> str:
    """Use generated PNG files for remaining EMF/WMF references."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rendered_dir = image_dir / "visio"
    for image in soup.find_all("img"):
        src = image.get("src")
        if not src:
            continue
        path = Path(urlparse(src).path.replace("\\", "/"))
        if path.suffix.lower() not in {".emf", ".wmf"}:
            continue
        rendered = rendered_dir / f"{path.stem}.png"
        if rendered.is_file() and rendered.stat().st_size:
            image["src"] = f"images/visio/{rendered.name}"
    return str(soup)


def _parse_word_document(document_xml: bytes) -> etree._Element:
    # Preserve namespace scopes, including prefixes used only in mc:Ignorable.
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        return etree.fromstring(document_xml, parser)
    except etree.XMLSyntaxError as exc:
        line, column = exc.position
        logging.getLogger(__name__).error(
            "Word XML parsing failed at line %s, column %s", line, column
        )
        # Parser diagnostics can contain document text. Expose only coordinates.
        raise ValueError(
            f"Word XML parsing failed at line {line}, column {column}"
        ) from None


def _serialize_word_document(
    root: etree._Element,
    promoted_fragments: dict[etree._Element, bytes] | None = None,
) -> bytes:
    """Preserve scoped namespace declarations and compatibility prefix values."""
    serialized = etree.tostring(root.getroottree(), encoding="utf-8", xml_declaration=True)
    if not promoted_fragments:
        return serialized
    # lxml reconciles namespace aliases when nodes are reparented. Restore
    # promoted subtrees from their pre-move XML, including QName-valued attributes.
    with minidom.parseString(serialized) as document:
        elements = [node for node in root.iter() if isinstance(node.tag, str)]
        dom_elements = list(document.getElementsByTagName("*"))
        for element, target in zip(elements, dom_elements, strict=True):
            fragment = promoted_fragments.get(element)
            if fragment is None:
                continue
            with minidom.parseString(fragment) as original:
                replacement = document.importNode(original.documentElement, deep=True)
            target.parentNode.replaceChild(replacement, target)
        return document.toxml(encoding="utf-8")


def _annotate_risky_word_graphics(source: Path, output_dir: Path) -> tuple[Path, dict[str, str]]:
    """Add lightweight warning markers after Word graphics that may not survive HTML conversion."""
    if not zipfile.is_zipfile(source):
        return source, {}
    with zipfile.ZipFile(source) as archive:
        document_part = "word/document.xml"
        if document_part not in archive.namelist():
            return source, {}
        document_xml = archive.read(document_part)

    root = _parse_word_document(document_xml)
    parent_map = {child: parent for parent in root.iter() for child in parent}
    paragraph_tag = f"{{{WORD_NS}}}p"
    textbox_tag = f"{{{WORD_NS}}}txbxContent"
    run_tag = f"{{{WORD_NS}}}r"
    text_tag = f"{{{WORD_NS}}}t"
    warnings: dict[str, str] = {}

    for paragraph in list(root.iter(paragraph_tag)):
        ancestor = parent_map.get(paragraph)
        inside_textbox = False
        while ancestor is not None:
            if ancestor.tag == textbox_tag:
                inside_textbox = True
                break
            ancestor = parent_map.get(ancestor)
        if inside_textbox:
            continue
        local_names = {etree.QName(element).localname for element in paragraph.iter() if isinstance(element.tag, str)}
        if not local_names.intersection({"OLEObject", "wgp", "group", "chart"}):
            continue
        parent = parent_map.get(paragraph)
        if parent is None:
            continue
        number = len(warnings) + 1
        marker = f"MANUALTOOLGRAPHICWARNING{number:04d}TOKEN"
        if "OLEObject" in local_names:
            message = (
                "変換上の注意: この位置には埋め込みオブジェクトがあります。"
                "HTMLでは内容や重ね合わせを完全に再現できない場合があるため、必要に応じて元のWord文書を確認してください。"
            )
        else:
            message = (
                "変換上の注意: この位置の図はWord上で複数の図形・画像・テキストを組み合わせています。"
                "HTMLでは一部の要素や配置を完全に再現できない場合があるため、必要に応じて元のWord文書を確認してください。"
            )
        warning_paragraph = etree.Element(paragraph_tag)
        warning_run = etree.SubElement(warning_paragraph, run_tag)
        warning_text = etree.SubElement(warning_run, text_tag)
        warning_text.text = marker
        parent.insert(list(parent).index(paragraph) + 1, warning_paragraph)
        warnings[marker] = message

    if not warnings:
        return source, {}
    prepared = output_dir / "word-graphics-warnings.docx"
    output_dir.mkdir(parents=True, exist_ok=True)
    rewritten = _serialize_word_document(root)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(prepared, "w") as converted:
        for item in original.infolist():
            converted.writestr(item, rewritten if item.filename == document_part else original.read(item.filename))
    return prepared, warnings


def _replace_graphic_warning_markers(html: str, warnings: dict[str, str]) -> str:
    if not warnings:
        return html
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for marker, message in warnings.items():
        for text in list(soup.find_all(string=lambda value: value and marker in value)):
            note = soup.new_tag("blockquote")
            paragraph = soup.new_tag("p")
            paragraph.string = message
            note.append(paragraph)
            if text.strip() == marker:
                container = text.parent
                if container and container.name == "p" and container.get_text(strip=True) == marker:
                    container.replace_with(note)
                else:
                    text.replace_with(note)
            else:
                before, after = text.split(marker, 1)
                text.replace_with(before, note, after)
    return str(soup)


def _word_paragraph_text(paragraph: etree._Element) -> str:
    parts: list[str] = []
    for element in paragraph.iter():
        if element.tag == f"{{{WORD_NS}}}t":
            parts.append(element.text or "")
        elif element.tag == f"{{{WORD_NS}}}tab":
            parts.append("\t")
        elif element.tag in {f"{{{WORD_NS}}}br", f"{{{WORD_NS}}}cr"}:
            parts.append("\n")
    return "".join(parts).strip()


def _strip_nested_graphics(paragraph: etree._Element) -> None:
    graphic_tags = {
        f"{{{WORD_NS}}}drawing",
        f"{{{WORD_NS}}}object",
        f"{{{WORD_NS}}}pict",
        f"{{{WORD_NS}}}txbxContent",
    }
    for parent in paragraph.iter():
        for child in list(parent):
            if child.tag in graphic_tags:
                parent.remove(child)


def _promote_textbox_content(source: Path, output_dir: Path) -> Path:
    """Create a conversion-only DOCX whose floating textbox text is ordinary content."""
    if not zipfile.is_zipfile(source):
        return source
    with zipfile.ZipFile(source) as archive:
        document_part = "word/document.xml"
        if document_part not in archive.namelist():
            return source
        document_xml = archive.read(document_part)

    root = _parse_word_document(document_xml)
    parent_map = {child: parent for parent in root.iter() for child in parent}
    textbox_tag = f"{{{WORD_NS}}}txbxContent"
    paragraph_tag = f"{{{WORD_NS}}}p"
    promoted = 0
    promoted_fragments: dict[etree._Element, bytes] = {}

    for paragraph in list(root.iter(paragraph_tag)):
        ancestor = parent_map.get(paragraph)
        inside_textbox = False
        while ancestor is not None:
            if ancestor.tag == textbox_tag:
                inside_textbox = True
                break
            ancestor = parent_map.get(ancestor)
        if inside_textbox:
            continue
        boxes = list(paragraph.iter(textbox_tag))
        if not boxes:
            continue
        parent = parent_map.get(paragraph)
        if parent is None:
            continue
        insert_at = list(parent).index(paragraph) + 1
        seen: set[str] = set()
        additions: list[etree._Element] = []
        for box in boxes:
            for textbox_paragraph in box.findall(f"./{paragraph_tag}"):
                text = _word_paragraph_text(textbox_paragraph)
                if not text or text in seen:
                    continue
                seen.add(text)
                clone = deepcopy(textbox_paragraph)
                _strip_nested_graphics(clone)
                if _word_paragraph_text(clone):
                    promoted_fragments[clone] = etree.tostring(clone, encoding="utf-8", with_tail=False)
                    additions.append(clone)
            box.clear()
        for addition in additions:
            parent.insert(insert_at, addition)
            insert_at += 1
            promoted += 1

    if not promoted:
        return source
    prepared = output_dir / "word-conversion.docx"
    output_dir.mkdir(parents=True, exist_ok=True)
    rewritten = _serialize_word_document(root, promoted_fragments)
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(prepared, "w") as converted:
        for item in original.infolist():
            converted.writestr(item, rewritten if item.filename == document_part else original.read(item.filename))
    return prepared


def _word_to_markdown(source: Path, output_dir: Path) -> str:
    annotated_source, graphic_warnings = _annotate_risky_word_graphics(source, output_dir)
    visio_assets = _extract_embedded_visio(source, output_dir)
    conversion_source = _promote_textbox_content(annotated_source, output_dir)
    pandoc = shutil.which("pandoc")
    try:
        if pandoc:
            image_dir = output_dir / "images"
            image_dir.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                [pandoc, str(conversion_source), "-f", "docx", "-t", "html5", "--mathml", "--wrap=none", "--extract-media", str(image_dir)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                html = _normalize_extracted_image_sources(result.stdout, image_dir)
                html = _replace_visio_previews(html, visio_assets)
                html = _unwrap_word_blockquotes(html)
                html = _replace_graphic_warning_markers(html, graphic_warnings)
                return html_to_hybrid_markdown(_replace_converted_metafiles(html, image_dir))

        try:
            import mammoth
        except ImportError as exc:
            raise RuntimeError("Word変換にはPandocまたはmammothが必要です。") from exc

        image_dir = output_dir / "images"
        image_dir.mkdir(parents=True, exist_ok=True)
        counter = 0

        def save_image(image):
            nonlocal counter
            counter += 1
            extension = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/gif": ".gif",
                "image/svg+xml": ".svg",
                "image/x-emf": ".emf",
                "image/x-wmf": ".wmf",
            }.get(image.content_type, ".bin")
            name = f"image_{counter:04d}{extension}"
            with image.open() as stream:
                content = stream.read()
            digest = hashlib.sha256(content).hexdigest()
            replacement = next((item[1] for item in visio_assets.values() if item[0] == digest), None)
            if replacement:
                return {"src": replacement}
            (image_dir / name).write_bytes(content)
            return {"src": f"images/{name}"}

        with conversion_source.open("rb") as stream:
            result = mammoth.convert_to_html(stream, convert_image=mammoth.images.img_element(save_image))
        html = _unwrap_word_blockquotes(result.value)
        return html_to_hybrid_markdown(_replace_graphic_warning_markers(html, graphic_warnings))
    finally:
        for temporary in {annotated_source, conversion_source}:
            if temporary != source:
                temporary.unlink(missing_ok=True)


def document_to_markdown(source: Path, output_dir: Path) -> str:
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"対応していない入力形式です: {suffix}（対応形式: {supported}）")
    if suffix == ".docx":
        return normalize_document_headings(_word_to_markdown(source, output_dir))
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("MarkdownとHTMLはUTF-8で保存してください。") from exc
    if suffix in {".html", ".htm"}:
        return normalize_document_headings(html_to_hybrid_markdown(_prepare_html_assets(source, output_dir, text)))
    return normalize_document_headings(text)
