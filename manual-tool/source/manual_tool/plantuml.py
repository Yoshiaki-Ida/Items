from __future__ import annotations

import base64
import os
import re
import subprocess
from pathlib import Path
from threading import BoundedSemaphore
from xml.etree import ElementTree


MAX_SOURCE_BYTES = 32_768
RUNTIME = Path(__file__).resolve().parent.parent / "runtime" / "plantuml"
_render_slots = BoundedSemaphore(2)


class PlantUmlError(ValueError):
    pass


def render_svg_uri(source: str) -> str:
    payload = source.encode('utf-8')
    if not source.strip() or len(payload) > MAX_SOURCE_BYTES:
        raise PlantUmlError('PlantUMLの入力が空か、32 KiBを超えています。')

    if not re.search(r'^\s*@startuml\b', source, re.I | re.M):
        payload = b'@startuml\n' + payload + b'\n@enduml\n'

    jar = Path(os.environ.get('MANUAL_TOOL_PLANTUML_JAR') or RUNTIME / 'plantuml.jar')
    if not jar.is_file():
        raise PlantUmlError('MANUAL_TOOL_PLANTUML_JAR にPlantUMLのJARを設定してください。')
    bundled_java = RUNTIME / 'java'
    java_home = os.environ.get('JAVA_HOME') or (bundled_java if bundled_java.is_dir() else None)
    java = str(Path(java_home) / 'bin' / 'java') if java_home else 'java'
    if not _render_slots.acquire(blocking=False):
        raise PlantUmlError('PlantUMLの変換が混み合っています。しばらく待って再試行してください。')
    try:
        result = subprocess.run(
            [java, '-Xmx256m', '-DPLANTUML_SECURITY_PROFILE=SANDBOX', '-jar', str(jar.resolve()),
             '-charset', 'UTF-8', '-tsvg', '-pipe', '-failfast2', '-nometadata'],
            input=payload, capture_output=True, timeout=15, check=False,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise PlantUmlError('PlantUMLの変換がタイムアウトしました。') from exc
    except OSError as exc:
        raise PlantUmlError('Javaを起動できません。JAVA_HOMEまたはPATHを確認してください。') from exc
    finally:
        _render_slots.release()

    if result.returncode or b'Syntax Error?' in result.stdout:
        raise PlantUmlError('PlantUMLを描画できません。構文とJavaの設定を確認してください。')
    try:
        svg = ElementTree.fromstring(result.stdout)
    except ElementTree.ParseError as exc:
        raise PlantUmlError('PlantUMLからSVGを1枚取得できませんでした。') from exc
    if svg.tag != '{http://www.w3.org/2000/svg}svg':
        raise PlantUmlError('PlantUMLからSVGを取得できませんでした。')
    return 'data:image/svg+xml;base64,' + base64.b64encode(result.stdout).decode('ascii')
