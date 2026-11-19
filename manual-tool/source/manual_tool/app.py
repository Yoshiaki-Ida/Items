from __future__ import annotations

import json
import hashlib
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

import yaml
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .assembly.builder import ManualValidationError, build_manual
from .assembly.project import CompositionProjectStore, stable_id
from .assembly.schema import ManualDefinition, load_manual, save_manual
from .assembly.validator import ID_PATTERN, validate_manual
from .converter import (
    SUPPORTED_EXTENSIONS,
    document_to_markdown,
    html_to_hybrid_markdown,
    normalize_document_headings,
)
from .lint_engine import apply_issue, lint_text
from .plantuml import MAX_SOURCE_BYTES, PlantUmlError, render_svg_uri
from .renderer import render_document
from .sessions import SessionStore
from .workspaces import WorkspaceStore


ROOT = Path(__file__).resolve().parent.parent
RULES = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
MAX_FILE_SIZE = 30 * 1024 * 1024
store = SessionStore()
workspace_store = WorkspaceStore()
composition_store = CompositionProjectStore()
app = FastAPI(title="ManualTool", version="0.1.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def disable_ui_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


class MarkdownUpdate(BaseModel):
    markdown: str


@app.api_route("/api/plantuml/render", methods=["OPTIONS", "POST"])
async def render_plantuml(request: Request):
    origin = request.headers.get("origin")
    if request.url.hostname != "127.0.0.1" or origin not in {
        None, "null", "http://127.0.0.1:8765"
    }:
        return Response(status_code=403)
    headers = {"Cache-Control": "no-store", "Vary": "Origin"}
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
    if request.method == "OPTIONS":
        headers["Access-Control-Allow-Methods"] = "POST"
        headers["Access-Control-Allow-Headers"] = "Content-Type"
        if request.headers.get("access-control-request-private-network") == "true":
            headers["Access-Control-Allow-Private-Network"] = "true"
        return Response(status_code=204, headers=headers)
    if request.headers.get("content-type") != "application/vnd.manual-tool.plantuml":
        return JSONResponse({"detail": "PlantUMLの入力形式が無効です。"}, 415, headers=headers)
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > MAX_SOURCE_BYTES:
            return JSONResponse({"detail": "PlantUMLの入力が32 KiBを超えています。"}, 413, headers=headers)
        payload.extend(chunk)
    try:
        svg = await run_in_threadpool(render_svg_uri, payload.decode("utf-8"))
    except UnicodeDecodeError:
        return JSONResponse({"detail": "PlantUMLの入力はUTF-8で送信してください。"}, 422, headers=headers)
    except PlantUmlError as exc:
        return JSONResponse({"detail": str(exc)}, 422, headers=headers)
    return JSONResponse({"svg": svg}, headers=headers)


class VisualHtmlUpdate(BaseModel):
    html: str


class ManualCompositionUpdate(BaseModel):
    title: str
    chapters: list[dict]
    output: str = "output/manual.html"


def _visible_issues(session):
    return [issue for issue in session.issues if issue.id not in session.ignored]


def _session_payload(session):
    return {
        "session_id": session.id,
        "filename": session.filename,
        "markdown": session.markdown,
        "issues": [issue.to_dict() for issue in _visible_issues(session)],
        "workspace_id": session.workspace_id,
        "relative_path": session.relative_path,
    }


def _issue_report_payload(session) -> list[dict]:
    return [
        {**issue.to_dict(), "ignored": issue.id in session.ignored}
        for issue in session.issues
    ]


def _markdown_table_cell(value: str) -> str:
    # Keep lint text literal, including pipe characters and Markdown syntax.
    escaped = re.sub(r"[&<>|\\`*_\[\]~!]", lambda match: f"&#{ord(match[0])};", value)
    return "<br>".join(escaped.splitlines())


def _issue_report_markdown(session) -> str:
    title = f"# 指摘一覧\n\n対象ファイル: {_markdown_table_cell(session.filename)}\n\n"
    issues = _visible_issues(session)
    if not issues:
        return title + "指摘はありません。\n"
    table = [
        "| 重要度 | 対象行 | ルール | 指摘内容 | 修正案 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for issue in issues:
        cells = (
            issue.level,
            str(issue.line) if issue.line else "文書全体",
            issue.rule,
            issue.message,
            issue.suggestion or "—",
        )
        table.append("| " + " | ".join(map(_markdown_table_cell, cells)) + " |")
    return title + "\n".join(table) + "\n"


def _get_session(session_id: str):
    try:
        return store.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


def _normalized_font_size(value: str) -> str | None:
    if not re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        return None
    size = float(value)
    if not 6 <= size <= 72:
        return None
    return f"{round(size * 2) / 2:g}"


def _normalized_table_point(value: str) -> str | None:
    if not re.fullmatch(r"\d+(?:\.\d+)?", value.strip()):
        return None
    size = float(value)
    if not 6 <= size <= 720:
        return None
    return f"{round(size * 2) / 2:g}"


def _normalized_cell_background(value: str) -> str | None:
    if value.lower() == "transparent":
        return "transparent"
    return value.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else None


def _visual_html_to_markdown(html: str, session_id: str) -> str:
    if len(html.encode("utf-8")) > MAX_FILE_SIZE:
        raise ValueError("編集内容は30MB以下にしてください。")
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article")
    content = article if article is not None else soup
    for forbidden in content.select("script, style, link, meta, iframe, object, embed, form, input, button"):
        forbidden.decompose()
    asset_prefix = f"/api/documents/{session_id}/assets/images/"
    for element in content.find_all(True):
        classes = [name for name in element.get("class", []) if name != "manual-tool-selected"]
        background = element.get("data-manual-tool-background", "")
        underline = element.get("data-manual-tool-underline", "")
        underline_color = element.get("data-manual-tool-underline-color", "")
        font_size = element.get("data-manual-tool-font-size", "")
        cell_background = element.get("data-manual-tool-cell-background", "")
        cell_width = element.get("data-manual-tool-cell-width", "")
        cell_height = element.get("data-manual-tool-cell-height", "")
        if element.name == "div" and "manual-text-row" in classes and not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
            style = element.get("style", "")
            match = re.search(r"(?:^|;)\s*background-color\s*:\s*(#[0-9a-fA-F]{6})\s*(?:;|$)", style)
            background = match.group(1) if match else ""
        underline_block = (element.name == "div" and "manual-text-row" in classes) or (
            element.name == "p" and "manual-underlined-block" in classes
        )
        if underline_block and underline not in {"thin", "thick"}:
            style = element.get("style", "")
            match = re.search(r"(?:^|;)\s*border-bottom\s*:\s*(1|3)(?:\.0)?pt\s+solid\s+(#[0-9a-fA-F]{6})\s*(?:;|$)", style, re.IGNORECASE)
            if match:
                underline = "thick" if match.group(1) == "3" else "thin"
                underline_color = match.group(2)
        if element.name == "p" and "manual-underlined-block" in classes and not (
            underline in {"thin", "thick"} and re.fullmatch(r"#[0-9a-fA-F]{6}", underline_color)
        ):
            classes.remove("manual-underlined-block")
            underline_block = False
        if element.name == "span" and "manual-font-size" in classes and _normalized_font_size(font_size) is None:
            style = element.get("style", "")
            match = re.search(r"(?:^|;)\s*font-size\s*:\s*(\d+(?:\.\d+)?)pt\s*(?:;|$)", style, re.IGNORECASE)
            font_size = match.group(1) if match else ""
        if element.name in {"th", "td"}:
            style = element.get("style", "")
            if _normalized_cell_background(cell_background) is None:
                match = re.search(r"(?:^|;)\s*background-color\s*:\s*(#[0-9a-fA-F]{6}|transparent)\s*(?:;|$)", style, re.IGNORECASE)
                cell_background = match.group(1) if match else ""
            if _normalized_table_point(cell_width) is None:
                match = re.search(r"(?:^|;)\s*width\s*:\s*(\d+(?:\.\d+)?)pt\s*(?:;|$)", style, re.IGNORECASE)
                cell_width = match.group(1) if match else ""
            if _normalized_table_point(cell_height) is None:
                match = re.search(r"(?:^|;)\s*height\s*:\s*(\d+(?:\.\d+)?)pt\s*(?:;|$)", style, re.IGNORECASE)
                cell_height = match.group(1) if match else ""
        for attribute in list(element.attrs):
            lowered = attribute.lower()
            if lowered == "style" or lowered == "contenteditable" or lowered.startswith("on") or lowered.startswith("data-manual-tool"):
                del element.attrs[attribute]
        if classes:
            element["class"] = classes
        elif element.has_attr("class"):
            del element["class"]
        if element.name == "div" and "manual-text-row" in classes:
            row_styles: list[str] = []
            if re.fullmatch(r"#[0-9a-fA-F]{6}", background):
                row_styles.append(f"background-color:{background.lower()}")
            if row_styles:
                element["style"] = ";".join(row_styles)
        if underline_block and underline in {"thin", "thick"} and re.fullmatch(r"#[0-9a-fA-F]{6}", underline_color):
            width = "3" if underline == "thick" else "1"
            underline_style = f"border-bottom:{width}pt solid {underline_color.lower()}"
            element["style"] = ";".join(filter(None, (element.get("style", ""), underline_style)))
        normalized_font_size = _normalized_font_size(font_size)
        if element.name == "span" and ({"manual-font-size", "manual-bold"} & set(classes)):
            font_styles: list[str] = []
            if "manual-font-size" in classes and normalized_font_size is not None:
                font_styles.append(f"font-size:{normalized_font_size}pt")
            if "manual-bold" in classes:
                font_styles.append("font-weight:700")
            if font_styles:
                element["style"] = ";".join(font_styles)
        if element.name in {"th", "td"}:
            cell_styles: list[str] = []
            normalized_cell_background = _normalized_cell_background(cell_background)
            normalized_cell_width = _normalized_table_point(cell_width)
            normalized_cell_height = _normalized_table_point(cell_height)
            if normalized_cell_background is not None:
                cell_styles.append(f"background-color:{normalized_cell_background}")
            if normalized_cell_width is not None:
                cell_styles.extend((f"width:{normalized_cell_width}pt", f"min-width:{normalized_cell_width}pt"))
            if normalized_cell_height is not None:
                cell_styles.append(f"height:{normalized_cell_height}pt")
            if cell_styles:
                element["style"] = ";".join(cell_styles)
        if element.name == "img":
            source = element.get("src", "")
            path = unquote(source.split("?", 1)[0])
            if path.startswith(asset_prefix):
                relative = path[len(asset_prefix):].replace("\\", "/").lstrip("/")
                if relative and ".." not in Path(relative).parts:
                    element["src"] = f"images/{relative}"
    return normalize_document_headings(html_to_hybrid_markdown(str(content)))


def _image_extension(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None


def _pick_directory(title: str) -> Path | None:
    root = None
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askdirectory(title=title, mustexist=True, parent=root)
    except Exception as exc:
        raise RuntimeError(f"フォルダ選択ダイアログを開けませんでした: {exc}") from exc
    finally:
        if root is not None:
            root.destroy()
    return Path(selected) if selected else None


def _pick_open_yaml(title: str) -> Path | None:
    root = None
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askopenfilename(
            title=title,
            filetypes=[("YAML", "*.yaml *.yml"), ("All files", "*.*")],
            parent=root,
        )
    except Exception as exc:
        raise RuntimeError(f"YAML選択ダイアログを開けませんでした: {exc}") from exc
    finally:
        if root is not None:
            root.destroy()
    return Path(selected) if selected else None


def _pick_save_yaml(title: str, initial_dir: Path) -> Path | None:
    root = None
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.asksaveasfilename(
            title=title,
            initialdir=str(initial_dir),
            initialfile="manual.yaml",
            defaultextension=".yaml",
            filetypes=[("YAML", "*.yaml"), ("YAML", "*.yml")],
            parent=root,
        )
    except Exception as exc:
        raise RuntimeError(f"YAML保存ダイアログを開けませんでした: {exc}") from exc
    finally:
        if root is not None:
            root.destroy()
    return Path(selected) if selected else None


def _composition_payload(project, definition: ManualDefinition | None = None):
    return {
        "project_id": project.id,
        "source_path": str(project.source_dir),
        "sources": [source.to_dict() for source in project.sources()],
        "definition": definition.to_mapping() if definition else None,
        "yaml_path": str(project.yaml_path) if project.yaml_path else None,
    }


def _assign_stable_chapter_ids(nodes: list[dict], used_ids: set[str] | None = None) -> list[dict]:
    if used_ids is None:
        used_ids = set()
    ordered_nodes = []
    for node in nodes:
        ordered = dict(node)
        candidate = str(ordered.get("id") or "").strip()
        if not ID_PATTERN.fullmatch(candidate) or candidate in used_ids:
            file_stem = Path(str(ordered.get("file") or "")).stem
            base = stable_id(file_stem or str(ordered.get("title") or ""), "section")
            if not ID_PATTERN.fullmatch(base):
                base = f"section-{base}"
            candidate = base
            suffix = 2
            while candidate in used_ids:
                candidate = f"{base}-{suffix}"
                suffix += 1
        used_ids.add(candidate)
        ordered["id"] = candidate
        ordered["numbered"] = ordered.get("numbered", True) is not False
        ordered["children"] = _assign_stable_chapter_ids(ordered.get("children") or [], used_ids)
        ordered_nodes.append(ordered)
    return ordered_nodes


def _definition_for_save(project, update: ManualCompositionUpdate, yaml_path: Path) -> ManualDefinition:
    yaml_root = yaml_path.resolve().parent
    try:
        relative_source = project.source_dir.relative_to(yaml_root)
    except ValueError as exc:
        raise ValueError("manual.yamlはHTMLフォルダ自身またはその親フォルダへ保存してください。") from exc
    mapping = {
        "version": 1,
        "manual": {
            "title": update.title,
            "source_dir": relative_source.as_posix() or ".",
            "output": update.output,
        },
        "chapters": _assign_stable_chapter_ids(update.chapters),
    }
    return ManualDefinition.from_mapping(mapping)


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")


@app.post("/api/manual-editor/pick-source")
def pick_manual_source():
    try:
        selected = _pick_directory("個別HTMLがあるフォルダを選択")
        if selected is None:
            return {"cancelled": True}
        selected = selected.resolve()
        yaml_path = selected / "manual.yaml"
        definition = None
        issues = []
        if yaml_path.is_file():
            definition = load_manual(yaml_path)
            source_dir = (yaml_path.parent / definition.source_dir).resolve()
            project = composition_store.create(source_dir, yaml_path)
            issues = validate_manual(definition, yaml_path)
        else:
            source_dir = selected / "source"
            if not source_dir.is_dir():
                source_dir = selected
            project = composition_store.create(source_dir, save_path=yaml_path)
    except (RuntimeError, NotADirectoryError) as exc:
        raise HTTPException(503, str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(422, f"manual.yamlを読み込めませんでした: {exc}") from exc
    return {
        "cancelled": False,
        **_composition_payload(project, definition),
        "issues": [issue.to_dict() for issue in issues],
    }


@app.post("/api/manual-editor/load-yaml")
def load_manual_yaml():
    try:
        yaml_path = _pick_open_yaml("編集するmanual.yamlを選択")
        if yaml_path is None:
            return {"cancelled": True}
        definition = load_manual(yaml_path)
        source_dir = (yaml_path.resolve().parent / definition.source_dir).resolve()
        project = composition_store.create(source_dir, yaml_path)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except (OSError, ValueError, NotADirectoryError) as exc:
        raise HTTPException(422, str(exc)) from exc
    issues = validate_manual(definition, yaml_path)
    return {
        "cancelled": False,
        **_composition_payload(project, definition),
        "issues": [issue.to_dict() for issue in issues],
    }


@app.post("/api/manual-editor/{project_id}/save")
def save_manual_yaml(project_id: str, update: ManualCompositionUpdate):
    try:
        project = composition_store.get(project_id)
        yaml_path = project.yaml_path or project.save_path or (project.source_dir / "manual.yaml")
        definition = _definition_for_save(project, update, yaml_path)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    issues = validate_manual(definition, yaml_path)
    if issues:
        return {"cancelled": False, "saved": False, "issues": [issue.to_dict() for issue in issues]}
    save_manual(yaml_path, definition)
    project.yaml_path = yaml_path.resolve()
    return {"saved": True, "yaml_path": str(yaml_path.resolve()), "issues": []}


@app.post("/api/manual-editor/{project_id}/build")
def build_current_manual(project_id: str):
    try:
        project = composition_store.get(project_id)
        if project.yaml_path is None:
            raise HTTPException(409, "先に現在の構成をYAMLへ保存してください。")
        definition = load_manual(project.yaml_path)
        issues = validate_manual(definition, project.yaml_path)
        if issues:
            return {
                "success": False,
                "yaml_path": str(project.yaml_path),
                "issues": [issue.to_dict() for issue in issues],
            }
        result = build_manual(definition, project.yaml_path)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (OSError, ValueError, ManualValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "success": True,
        "yaml_path": str(project.yaml_path),
        "output_path": str(result.output_path),
        "heading_count": len(result.headings),
        "issues": [],
    }


@app.get("/api/manual-editor/{project_id}/preview/{relative_path:path}", response_class=HTMLResponse)
def preview_manual_source(project_id: str, relative_path: str):
    try:
        project = composition_store.get(project_id)
        source = project.resolve_source(relative_path)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    html = source.read_text(encoding="utf-8")
    base_path = source.parent.relative_to(project.source_dir).as_posix()
    prefix = f"/api/manual-editor/{project.id}/assets"
    base_url = f"{prefix}/{base_path}/" if base_path != "." else f"{prefix}/"
    base = f'<base href="{base_url}">'
    html = html.replace("<head>", f"<head>{base}", 1) if "<head>" in html else f"{base}{html}"
    return HTMLResponse(html)


@app.get("/api/manual-editor/{project_id}/assets/{relative_path:path}")
def manual_source_asset(project_id: str, relative_path: str):
    try:
        project = composition_store.get(project_id)
        target = project.resolve_asset(relative_path)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(target)


@app.post("/api/manual-build/pick-yaml")
def build_from_selected_yaml():
    try:
        yaml_path = _pick_open_yaml("構築するmanual.yamlを選択")
        if yaml_path is None:
            return {"cancelled": True}
        definition = load_manual(yaml_path)
        issues = validate_manual(definition, yaml_path)
        if issues:
            return {
                "cancelled": False,
                "success": False,
                "yaml_path": str(yaml_path.resolve()),
                "issues": [issue.to_dict() for issue in issues],
            }
        result = build_manual(definition, yaml_path)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except (OSError, ValueError, ManualValidationError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "cancelled": False,
        "success": True,
        "yaml_path": str(yaml_path.resolve()),
        "output_path": str(result.output_path),
        "heading_count": len(result.headings),
        "issues": [],
    }


@app.post("/api/workspaces/pick")
def pick_workspace():
    try:
        selected = _pick_directory("ManualToolで開くフォルダを選択")
        if selected is None:
            return {"cancelled": True}
        workspace = workspace_store.create(selected)
    except (RuntimeError, NotADirectoryError) as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "cancelled": False,
        "workspace_id": workspace.id,
        "name": workspace.root.name,
        "path": str(workspace.root),
        "files": workspace.files(),
    }


@app.post("/api/workspaces/{workspace_id}/documents/{relative_path:path}")
def open_workspace_document(workspace_id: str, relative_path: str):
    try:
        workspace = workspace_store.get(workspace_id)
        source = workspace.resolve_file(relative_path)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

    session = store.create(
        source.name,
        "",
        workspace_id=workspace.id,
        relative_path=source.relative_to(workspace.root).as_posix(),
    )
    try:
        session.markdown = document_to_markdown(source, session.directory)
    except (ValueError, RuntimeError) as exc:
        store.delete(session.id)
        raise HTTPException(422, str(exc)) from exc
    session.issues = lint_text(session.markdown, RULES)
    store.save(session)
    return _session_payload(session)


@app.post("/api/documents")
async def create_documents(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "ファイルを選択してください。")
    documents = []
    errors = []
    for upload in files:
        safe_name = Path(upload.filename or "manual").name
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            errors.append({"filename": safe_name, "message": "対応形式は.docx、.md、.markdown、.html、.htmです。"})
            continue
        raw = await upload.read()
        if len(raw) > MAX_FILE_SIZE:
            errors.append({"filename": safe_name, "message": "ファイルサイズは30MB以下にしてください。"})
            continue
        session = store.create(safe_name, "")
        source = session.directory / safe_name
        try:
            source.write_bytes(raw)
            session.markdown = document_to_markdown(source, session.directory)
        except (OSError, ValueError, RuntimeError) as exc:
            store.delete(session.id)
            errors.append({"filename": safe_name, "message": str(exc)})
            continue
        session.issues = lint_text(session.markdown, RULES)
        store.save(session)
        documents.append(_session_payload(session))
    if not documents:
        raise HTTPException(400, {"errors": errors})
    return {"documents": documents, "errors": errors}


@app.put("/api/documents/{session_id}")
def update_document(session_id: str, update: MarkdownUpdate):
    session = _get_session(session_id)
    session.markdown = update.markdown
    session.issues = lint_text(session.markdown, RULES)
    store.save(session)
    return _session_payload(session)


@app.put("/api/documents/{session_id}/visual-edit")
def update_document_from_visual_html(session_id: str, update: VisualHtmlUpdate):
    session = _get_session(session_id)
    try:
        session.markdown = _visual_html_to_markdown(update.html, session_id)
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    session.issues = lint_text(session.markdown, RULES)
    store.save(session)
    return _session_payload(session)


@app.post("/api/documents/{session_id}/assets/images")
async def upload_replacement_image(session_id: str, file: UploadFile = File(...)):
    session = _get_session(session_id)
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, "画像ファイルは30MB以下にしてください。")
    extension = _image_extension(content)
    if extension is None:
        raise HTTPException(415, "PNG、JPEG、GIF、WebP画像を選択してください。")
    original_stem = Path(file.filename or "image").stem
    safe_stem = re.sub(r"[^0-9A-Za-z_-]+", "-", original_stem).strip("-")[:48] or "image"
    digest = hashlib.sha256(content).hexdigest()[:12]
    relative = Path("replacements") / f"{safe_stem}-{digest}{extension}"
    target = session.directory / "images" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    asset_path = f"images/{relative.as_posix()}"
    return {
        "path": asset_path,
        "preview_url": f"/api/documents/{session_id}/assets/images/{relative.as_posix()}",
    }


@app.post("/api/documents/{session_id}/issues/{issue_id}/apply")
def apply_suggestion(session_id: str, issue_id: str):
    session = _get_session(session_id)
    try:
        issue = next(item for item in session.issues if item.id == issue_id)
        session.markdown = apply_issue(session.markdown, issue)
    except StopIteration as exc:
        raise HTTPException(404, "指摘が見つかりません。") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.issues = lint_text(session.markdown, RULES)
    store.save(session)
    return _session_payload(session)


@app.post("/api/documents/{session_id}/issues/{issue_id}/ignore")
def ignore_issue(session_id: str, issue_id: str):
    session = _get_session(session_id)
    session.ignored.add(issue_id)
    store.save(session)
    return _session_payload(session)


@app.post("/api/documents/{session_id}/preview", response_class=HTMLResponse)
def preview(session_id: str, update: MarkdownUpdate):
    session = _get_session(session_id)
    return render_document(
        normalize_document_headings(update.markdown),
        Path(session.filename).stem,
        image_base=f"/api/documents/{session_id}/assets/images",
    )


@app.get("/api/documents/{session_id}/assets/images/{asset_path:path}")
def session_image(session_id: str, asset_path: str):
    session = _get_session(session_id)
    image_root = (session.directory / "images").resolve()
    target = (image_root / asset_path).resolve()
    try:
        target.relative_to(image_root)
    except ValueError as exc:
        raise HTTPException(404, "画像が見つかりません。") from exc
    if not target.is_file():
        raise HTTPException(404, "画像が見つかりません。")
    return FileResponse(target)


@app.get("/api/documents/{session_id}/download/{kind}")
def download(session_id: str, kind: str):
    session = _get_session(session_id)
    stem = Path(session.filename).stem
    normalized_markdown = normalize_document_headings(session.markdown)
    if kind == "markdown":
        return Response(normalized_markdown, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{stem}_fixed.md"'})
    if kind == "html":
        html = render_document(normalized_markdown, stem, image_dir=session.directory / "images")
        return Response(html, media_type="text/html", headers={"Content-Disposition": f'attachment; filename="{stem}.html"'})
    if kind == "report":
        data = json.dumps(_issue_report_payload(session), ensure_ascii=False, indent=2)
        return Response(data, media_type="application/json", headers={"Content-Disposition": 'attachment; filename="lint-report.json"'})
    if kind == "report-markdown":
        return Response(
            _issue_report_markdown(session),
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="lint-report.md"'},
        )
    raise HTTPException(404, "ダウンロード形式が不正です。")


@app.post("/api/documents/{session_id}/export")
def export_document(session_id: str):
    session = _get_session(session_id)
    try:
        selected = _pick_directory("ManualToolの書き出し先フォルダを選択")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    if selected is None:
        return {"cancelled": True}

    relative = Path(session.relative_path) if session.relative_path else Path(session.filename)
    output_dir = selected.resolve()
    support_dir = output_dir / f"{relative.stem}_manual"
    exported_image_dir = output_dir / "images" / relative.stem
    exported_visio_dir = output_dir / "visio" / relative.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    support_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = support_dir / f"{relative.stem}_fixed.md"
    html_path = output_dir / f"{relative.stem}.html"
    report_path = support_dir / "lint-report.json"
    normalized_markdown = normalize_document_headings(session.markdown)
    exported_markdown = (
        normalized_markdown
        .replace("](images/", f"](../images/{relative.stem}/")
        .replace('src="images/', f'src="../images/{relative.stem}/')
        .replace("src='images/", f"src='../images/{relative.stem}/")
    )
    markdown_path.write_text(exported_markdown, encoding="utf-8")
    html_path.write_text(
        render_document(normalized_markdown, relative.stem, image_base=f"images/{relative.stem}"),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(_issue_report_payload(session), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (support_dir / "lint-report.md").write_text(_issue_report_markdown(session), encoding="utf-8")
    source_images = session.directory / "images"
    if source_images.is_dir():
        shutil.copytree(source_images, exported_image_dir, dirs_exist_ok=True)
    source_visio = session.directory / "visio"
    if source_visio.is_dir():
        shutil.copytree(source_visio, exported_visio_dir, dirs_exist_ok=True)
    result = {
        "cancelled": False,
        "output_dir": str(output_dir),
        "support_dir": str(support_dir),
        "image_dir": str(exported_image_dir) if source_images.is_dir() else None,
        "visio_dir": str(exported_visio_dir) if source_visio.is_dir() else None,
        "markdown_path": str(markdown_path),
        "html_path": str(html_path),
    }
    store.delete(session_id)
    return result
