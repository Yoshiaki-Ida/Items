from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup, Tag

from ..renderer import LEGACY_DOCUMENT_STYLE, STYLE as DOCUMENT_STYLE
from .html_parser import body_nodes, heading_level, read_html, strip_heading_number
from .project import stable_id
from .schema import ManualDefinition, ManualNode, load_manual
from .validator import ASSET_ATTRIBUTES, ValidationIssue, validate_manual


@dataclass(frozen=True)
class BuildResult:
    output_path: Path
    issues: tuple[ValidationIssue, ...]
    headings: tuple[dict, ...]


class ManualValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("\n".join(issue.message for issue in issues))


def _format_number(number: tuple[int, ...]) -> str:
    return f"{'.'.join(map(str, number))}." if number else ""


def _is_external(reference: str) -> bool:
    parsed = urlparse(reference)
    return bool(parsed.scheme or parsed.netloc or reference.startswith(("//", "#")))


def _copy_and_rewrite_assets(soup: BeautifulSoup, source: Path, project_root: Path, output_dir: Path) -> set[str]:
    generated: set[str] = set()
    for tag_name, attribute in ASSET_ATTRIBUTES:
        for tag in soup.find_all(tag_name):
            reference = tag.get(attribute)
            if not reference or _is_external(reference):
                continue
            parsed = urlparse(reference)
            target = (source.parent / unquote(parsed.path)).resolve()
            relative = target.relative_to(project_root)
            destination = output_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
            generated.add(relative.as_posix())
            suffix = f"?{parsed.query}" if parsed.query else ""
            suffix += f"#{parsed.fragment}" if parsed.fragment else ""
            tag[attribute] = relative.as_posix() + suffix
    return generated


def _load_generated_files(report_path: Path) -> set[str]:
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return set()
    values = data.get("generated_files", []) if isinstance(data, dict) else []
    return {value for value in values if isinstance(value, str) and value}


def _remove_stale_generated_files(output_dir: Path, stale_files: set[str]) -> None:
    output_root = output_dir.resolve()
    for relative_name in sorted(stale_files, reverse=True):
        relative = Path(relative_name)
        if relative.is_absolute():
            continue
        target = (output_root / relative).resolve()
        try:
            target.relative_to(output_root)
        except ValueError:
            continue
        if target.is_file():
            target.unlink()
        parent = target.parent
        while parent != output_root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _toc_html(entries: list[dict]) -> str:
    roots: list[dict] = []
    stack: list[tuple[int, list[dict]]] = [(0, roots)]
    for entry in entries:
        level = entry["toc_level"]
        while stack[-1][0] >= level:
            stack.pop()
        item = {"entry": entry, "children": []}
        stack[-1][1].append(item)
        stack.append((level, item["children"]))

    def render(items: list[dict]) -> str:
        if not items:
            return ""
        rows = []
        for item in items:
            entry = item["entry"]
            number = _format_number(entry["number"])
            label = f"{number} {escape(entry['title'])}" if number else escape(entry["title"])
            target = escape(entry["id"])
            rows.append(
                f'<li><a href="#{target}"><span class="toc-label">{label}</span>'
                f'<span class="toc-leader" aria-hidden="true"></span>'
                f'<span class="toc-page" data-target="{target}" aria-label="ページ">–</span>'
                f'</a>{render(item["children"])}</li>'
            )
        return f"<ol>{''.join(rows)}</ol>"

    return render(roots)


def build_manual(definition_or_path: ManualDefinition | Path, yaml_path: Path | None = None) -> BuildResult:
    if isinstance(definition_or_path, Path):
        yaml_path = definition_or_path.resolve()
        definition = load_manual(yaml_path)
    else:
        definition = definition_or_path
        if yaml_path is None:
            raise ValueError("ManualDefinitionを構築する場合はyaml_pathが必要です。")
        yaml_path = yaml_path.resolve()
    issues = validate_manual(definition, yaml_path)
    if issues:
        raise ManualValidationError(issues)

    project_root = yaml_path.parent
    source_root = (project_root / definition.source_dir).resolve()
    output_path = (project_root / definition.output).resolve()
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "build-report.json"
    previous_generated_files = _load_generated_files(report_path)
    generated_files: set[str] = set()
    project_assets = project_root / "assets"
    if project_assets.is_dir():
        try:
            output_dir.relative_to(project_assets.resolve())
        except ValueError:
            shutil.copytree(project_assets, output_dir / "assets", dirs_exist_ok=True)
            generated_files.update(
                path.relative_to(project_root).as_posix()
                for path in project_assets.rglob("*")
                if path.is_file()
            )

    headings: list[dict] = []
    styles: list[str] = []
    seen_styles: set[str] = set()
    structural_ids = {node.id for node in definition.chapters}

    def collect_ids(nodes: list[ManualNode]) -> None:
        for item in nodes:
            structural_ids.add(item.id)
            collect_ids(item.children)

    collect_ids(definition.chapters)
    used_anchor_ids: set[str] = set(structural_ids)

    def unique_anchor(base: str) -> str:
        candidate = base
        suffix = 2
        while candidate in used_anchor_ids:
            candidate = f"{base}-{suffix}"
            suffix += 1
        used_anchor_ids.add(candidate)
        return candidate

    def render_nodes(
        nodes: list[ManualNode],
        parent_number: tuple[int, ...],
        depth: int = 1,
        starting_index: int = 0,
    ) -> str:
        rendered: list[str] = []
        numbered_index = starting_index
        for node in nodes:
            node_title = strip_heading_number(node.title)
            if node.numbered:
                numbered_index += 1
            number = parent_number + (numbered_index,) if node.numbered else parent_number
            heading_id = node.id
            heading_tag = min(depth + 1, 6)
            content = [f'<section class="manual-section level-{depth}" data-node-id="{escape(node.id)}">']
            heading_text = f"{_format_number(number)} {node_title}" if node.numbered else node_title
            headings.append(
                {
                    "id": heading_id,
                    "title": node_title,
                    "number": number if node.numbered else (),
                    "numbered": node.numbered,
                    "toc_level": depth,
                    "kind": "structure",
                }
            )
            content.append(f'<h{heading_tag} id="{escape(heading_id)}">{escape(heading_text)}</h{heading_tag}>')
            child_starting_index = 0
            if node.file:
                source = (source_root / node.file).resolve()
                part = read_html(source)
                for control in part.soup.select(
                    "script[data-plantuml-script], .plantuml-toolbar:has([data-plantuml-save]), "
                    "figure[data-plantuml-diagram] .plantuml-editor"
                ):
                    control.decompose()
                for style in part.soup.find_all("style"):
                    css = style.get_text().strip()
                    is_document_style = style.has_attr("data-manual-tool-document-style") or css in {
                        DOCUMENT_STYLE.strip(),
                        LEGACY_DOCUMENT_STYLE.strip(),
                    }
                    if not css or is_document_style or css in seen_styles:
                        continue
                    seen_styles.add(css)
                    styles.append(css)
                first_h1 = next((heading for heading in part.headings if heading.name == "h1"), None)
                if first_h1:
                    first_h1.decompose()
                if node.numbered:
                    child_starting_index = sum(heading.name == "h2" for heading in part.headings)
                    counters: list[int] = []
                    for heading in part.soup.find_all(["h2", "h3", "h4", "h5", "h6"]):
                        relative_level = heading_level(heading) - 1
                        while len(counters) < relative_level:
                            counters.append(0)
                        counters = counters[:relative_level]
                        counters[-1] += 1
                        internal_number = number + tuple(counters)
                        title = strip_heading_number(heading.get_text(" ", strip=True))
                        original_id = str(heading.get("id", "")).strip()
                        anchor_base = f"{node.id}--{original_id or stable_id(title, 'heading')}"
                        anchor = unique_anchor(anchor_base)
                        new_level = min(depth + relative_level + 1, 6)
                        heading.name = f"h{new_level}"
                        heading["id"] = anchor
                        heading.string = f"{_format_number(internal_number)} {title}"
                        headings.append(
                            {
                                "id": anchor,
                                "title": title,
                                "number": internal_number,
                                "numbered": True,
                                "toc_level": depth + relative_level,
                                "kind": "content",
                            }
                        )
                else:
                    for heading in part.soup.find_all(["h2", "h3", "h4", "h5", "h6"]):
                        relative_level = heading_level(heading) - 1
                        title = strip_heading_number(heading.get_text(" ", strip=True))
                        original_id = str(heading.get("id", "")).strip()
                        anchor_base = f"{node.id}--{original_id or stable_id(title, 'heading')}"
                        anchor = unique_anchor(anchor_base)
                        heading.name = f"h{min(depth + relative_level + 1, 6)}"
                        heading["id"] = anchor
                        heading.string = title
                        headings.append(
                            {
                                "id": anchor,
                                "title": title,
                                "number": (),
                                "numbered": False,
                                "toc_level": depth + relative_level,
                                "kind": "content",
                            }
                        )
                generated_files.update(_copy_and_rewrite_assets(part.soup, source, project_root, output_dir))
                content.extend(str(item) for item in body_nodes(part))
            content.append(render_nodes(node.children, number, depth + 1, child_starting_index))
            content.append("</section>")
            rendered.append("".join(content))
        return "".join(rendered)

    body = render_nodes(definition.chapters, ())
    combined = BeautifulSoup(body, "html.parser")
    node_lookup = {entry["id"]: entry for entry in headings if entry["kind"] == "structure"}
    for reference in combined.find_all("a", attrs={"data-ref": True}):
        target = node_lookup.get(str(reference.get("data-ref")))
        if target:
            reference["href"] = f'#{target["id"]}'
            if not reference.get_text(strip=True):
                number = _format_number(target["number"])
                reference.string = f"{number} {target['title']}" if number else target["title"]

    toc = _toc_html(headings)
    extra_styles = "\n".join(styles)
    base_styles = """
:root{--paper-width:210mm;--paper-height:297mm;--paper-padding-top:16mm;--paper-padding-right:18mm;--paper-padding-bottom:20mm;--paper-padding-left:18mm}
*{box-sizing:border-box}html{background:#dfe5eb}body{margin:0;color:#243447;font-family:'Yu Gothic UI',Meiryo,sans-serif;line-height:1.75;background:#dfe5eb;padding:12mm 0}
.a4-paper{width:var(--paper-width);min-height:var(--paper-height);margin:0 auto 10mm;padding:var(--paper-padding-top) var(--paper-padding-right) var(--paper-padding-bottom) var(--paper-padding-left);background:#fff;box-shadow:0 3mm 9mm #2030402b}.manual-page{height:var(--paper-height)}.manual-page-body{height:calc(var(--paper-height) - var(--paper-padding-top) - var(--paper-padding-bottom));overflow:hidden}.manual-page.oversize,.manual-page.oversize .manual-page-body{height:auto;min-height:calc(var(--paper-height) - var(--paper-padding-top) - var(--paper-padding-bottom));overflow:visible}#paged-content:empty{display:none}
h1,h2,h3,h4,h5,h6{scroll-margin-top:16px;color:#17365d;break-after:avoid-page}h1{border-bottom:3px solid #17365d;padding-bottom:.3em}h2,h3{border-bottom:1px solid #d9e2ec}
nav.toc{background:#f4f7fa;border:1px solid #d9e2ec;padding:8mm;margin:8mm 0}nav.toc ol{list-style:none;padding-left:0;margin:.35em 0}nav.toc ol ol{padding-left:1.5em}nav.toc li{break-inside:avoid}nav.toc a{display:flex;align-items:baseline;gap:.35em;color:#175cd3;text-decoration:none}.toc-label{min-width:0}.toc-leader{flex:1 1 auto;border-bottom:1px dotted #718497;transform:translateY(-.25em)}.toc-page{flex:0 0 auto;min-width:2em;text-align:right;color:#243447;font-variant-numeric:tabular-nums}
table{width:100%;margin:1em 0;border-collapse:collapse;break-inside:avoid}th,td{padding:8px;border:1px solid #9fb3c8;vertical-align:top}th{background:#eaf2f8;font-weight:700}.manual-table-points{width:auto;table-layout:fixed}img{max-width:100%;height:auto}pre{overflow:auto;padding:16px;border-radius:6px;background:#17202a;color:#f4f6f7}blockquote{margin:1em 0;padding:12px 16px;border-left:4px solid #2684ff;border-radius:0 5px 5px 0;background:#eef6ff;color:#52667a}.manual-text-row{margin:1em 0;padding:8px 10px}.manual-text-row>p{margin:0}.manual-section{margin-top:28px}
@page{size:A4;margin:16mm 18mm 20mm}
@media print{html,body{background:#fff;padding:0}.a4-paper{width:auto;min-height:0;margin:0;padding:0;box-shadow:none}.front-matter,.manual-page{height:auto;min-height:0;break-after:page}.manual-page-body{height:auto;overflow:visible}.manual-content{break-after:page}.manual-content>.manual-section.level-1:not(:first-child){break-before:page}nav.toc{background:transparent}a{color:inherit!important;text-decoration:none!important}}
"""
    pagination_script = """<script>
(() => {
  const flattenSections = root => {
    const blocks = [];
    const collect = container => [...container.childNodes].forEach(node => {
      if (node.nodeType === Node.ELEMENT_NODE && node.matches('section.manual-section, article')) {
        if (node.matches('section.manual-section.level-1')) blocks.push({chapterBreak: true});
        collect(node);
      }
      else if (node.nodeType === Node.ELEMENT_NODE) blocks.push(node);
      else if (node.textContent.trim()) {
        const block = document.createElement('div');
        block.textContent = node.textContent;
        blocks.push(block);
      }
    });
    collect(root);
    return blocks;
  };
  const paginateManual = () => {
    const source = document.querySelector('.manual-content');
    const destination = document.getElementById('paged-content');
    if (!source || !destination || destination.children.length) return;
    const blocks = flattenSections(source);
    let pageNumber = 0;
    let page;
    let pageBody;
    const addPage = () => {
      pageNumber += 1;
      page = document.createElement('section');
      page.className = 'a4-paper manual-page';
      page.dataset.page = String(pageNumber);
      pageBody = document.createElement('div');
      pageBody.className = 'manual-page-body';
      page.appendChild(pageBody);
      destination.appendChild(page);
    };
    const placeTableByRows = table => {
      const rows = [...table.querySelectorAll(':scope > tbody > tr')];
      if (!rows.length || table.querySelector(':scope > tbody [rowspan]')) return false;
      const makeTable = () => {
        const fragment = table.cloneNode(false);
        [...table.children].forEach(child => {
          if (child.tagName === 'COLGROUP' || child.tagName === 'THEAD' || child.tagName === 'CAPTION') {
            fragment.appendChild(child.cloneNode(true));
          }
        });
        const body = document.createElement('tbody');
        fragment.appendChild(body);
        pageBody.appendChild(fragment);
        return {fragment, body};
      };
      let current = makeTable();
      let rowsOnPage = 0;
      rows.forEach(row => {
        current.body.appendChild(row);
        if (pageBody.scrollHeight <= pageBody.clientHeight + 1) {
          rowsOnPage += 1;
          return;
        }
        current.body.removeChild(row);
        if (!rowsOnPage) current.fragment.remove();
        addPage();
        current = makeTable();
        current.body.appendChild(row);
        rowsOnPage = 1;
        if (pageBody.scrollHeight > pageBody.clientHeight + 1) page.classList.add('oversize');
      });
      return true;
    };
    addPage();
    blocks.forEach(block => {
      if (block.chapterBreak) {
        if (pageBody.children.length) addPage();
        return;
      }
      if (block.tagName === 'TABLE' && placeTableByRows(block)) return;
      pageBody.appendChild(block);
      if (pageBody.scrollHeight <= pageBody.clientHeight + 1) return;
      pageBody.removeChild(block);
      if (!pageBody.children.length) {
        pageBody.appendChild(block);
        page.classList.add('oversize');
        return;
      }
      addPage();
      pageBody.appendChild(block);
      if (pageBody.scrollHeight > pageBody.clientHeight + 1) page.classList.add('oversize');
    });
    source.remove();
    document.querySelectorAll('.toc-page[data-target]').forEach(pageCell => {
      const target = document.getElementById(pageCell.dataset.target);
      const targetPage = target?.closest('.manual-page');
      if (targetPage) pageCell.textContent = targetPage.dataset.page;
    });
  };
  window.addEventListener('load', async () => {
    if (document.fonts?.ready) await document.fonts.ready;
    requestAnimationFrame(() => requestAnimationFrame(paginateManual));
  });
})();
</script>"""
    html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(definition.title)}</title>
<style>
{base_styles}
{extra_styles}
</style></head><body>
<section class="a4-paper front-matter"><h1>{escape(definition.title)}</h1><nav class="toc" aria-label="目次"><h2>目次</h2>{toc}</nav></section>
<main class="a4-paper manual-content">{str(combined)}</main><div id="paged-content"></div>{pagination_script}
</body></html>"""
    output_path.write_text(html, encoding="utf-8")
    _remove_stale_generated_files(output_dir, previous_generated_files - generated_files)
    report_path.write_text(
        json.dumps(
            {
                "output": str(output_path),
                "headings": headings,
                "generated_files": sorted(generated_files),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return BuildResult(output_path, tuple(), tuple(headings))
