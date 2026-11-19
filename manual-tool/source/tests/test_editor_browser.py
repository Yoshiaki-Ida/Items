from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest


@pytest.fixture
def browser_page(client):
    playwright = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("MANUALTOOL_TEST_BROWSER")
    if not executable or not Path(executable).is_file():
        pytest.skip("Set MANUALTOOL_TEST_BROWSER to a Chromium/Edge executable")
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 850})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route_request(route):
            request = route.request
            url = urlsplit(request.url)
            response = client.request(
                request.method, url.path + ("?" + url.query if url.query else ""),
                content=request.post_data_buffer,
                headers={"content-type": request.headers.get("content-type", "")},
            )
            headers = {key: value for key, value in response.headers.items()
                       if key not in {"content-length", "content-encoding"}}
            route.fulfill(status=response.status_code, headers=headers, body=response.content)

        page.route("http://manualtool.test/**", route_request)
        page.goto("http://manualtool.test/")
        page.locator("#chooseDocumentEditor").click()
        yield page
        assert not errors
        browser.close()


def load_markdown(page, client, markdown):
    response = client.post("/api/documents", files=[("files", ("manual.md", markdown.encode(), "text/markdown"))])
    assert response.status_code == 200
    payload = response.json()["documents"][0]
    page.evaluate("payload => loadPayload(payload)", payload)
    page.wait_for_function("document.getElementById('preview').contentDocument?.querySelector('article')")
    page.wait_for_function("!document.querySelector('.preview-frame-pending')")
    return payload


def test_sidebar_drag_keyboard_persistence_and_source_gutter(browser_page, client):
    page = browser_page
    load_markdown(page, client, "# Heading\n\n" + "\n".join(f"Line {i}" for i in range(150)))
    sidebar = page.locator("#sidebarResizer")
    before = page.locator("main aside").bounding_box()["width"]
    bounds = sidebar.bounding_box()
    page.mouse.move(bounds["x"] + 3, bounds["y"] + 80)
    page.mouse.down()
    page.mouse.move(bounds["x"] + 100, bounds["y"] + 80, steps=5)
    page.mouse.up()
    after = page.locator("main aside").bounding_box()["width"]
    assert after > before + 80
    sidebar.focus()
    page.keyboard.press("ArrowRight")
    assert page.locator("main aside").bounding_box()["width"] == pytest.approx(after + 24, abs=1)
    saved = page.evaluate("localStorage.getItem('manualToolSidebarWidth')")
    count = page.locator("#editor").input_value().count("\n") + 1
    assert page.locator("#lineNumberContent").inner_text().splitlines()[-1] == str(count)
    page.locator("#editor").evaluate("element => { element.scrollTop = 500; element.dispatchEvent(new Event('scroll')); }")
    assert page.locator("#lineNumberContent").evaluate("element => getComputedStyle(element).transform") != "none"
    # Source lines remain aligned when a single line is wider than the editor.
    page.locator("#editor").fill("x" * 500 + "\nsecond\n")
    assert page.locator("#lineNumberContent").inner_text() == "1\n2\n3"
    assert page.locator("#editor").evaluate("element => element.scrollWidth > element.clientWidth")
    page.reload()
    page.locator("#chooseDocumentEditor").click()
    assert page.evaluate("localStorage.getItem('manualToolSidebarWidth')") == saved
    assert page.locator("main aside").bounding_box()["width"] == pytest.approx(float(saved), abs=1)


def test_issue_navigation_keeps_preview_and_selects_source_line(browser_page, client):
    page = browser_page
    markdown = "# Overview\n\n" + "\n\n".join(f"Paragraph {i}." for i in range(50)) + "\n\n### Target heading\n\nTarget body.\n"
    payload = load_markdown(page, client, markdown)
    issue = next(item for item in payload["issues"] if item["rule"] == "heading-jump")
    page.locator('[data-panel="previewPanel"]').click()
    page.wait_for_function("!document.querySelector('.preview-frame-pending')")
    page.locator(".issue").filter(has_text=issue["message"]).click()
    assert page.locator("#previewPanel").is_visible()
    assert not page.locator("#editPanel").is_visible()
    target = page.frame_locator("#preview").locator("h3").filter(has_text="Target heading")
    assert 0 <= target.bounding_box()["y"] < 850
    page.locator('[data-panel="editPanel"]').click()
    page.locator(".issue").filter(has_text=issue["message"]).click()
    selected = page.locator("#editor").evaluate("element => element.value.slice(element.selectionStart, element.selectionEnd)")
    assert "Target heading" in selected
    assert page.locator("#editPanel").is_visible()


def test_preview_mapping_distinguishes_repeated_titles_and_table_rows(browser_page, client):
    page = browser_page
    load_markdown(page, client, "# Heading\n\n## Same\n\nFirst\n\n## Same\n\nSecond\n\n| A | B |\n| --- | --- |\n| X | Y |\n")
    result = page.evaluate(r"""() => {
      const frame = document.getElementById("preview");
      const lines = document.getElementById("editor").value.split("\n");
      const titles = lines.map((line, index) => line.includes("Same") ? index : -1).filter(index => index >= 0);
      return titles.map(index => {
        const target = previewIssueTarget(frame, lines, index);
        return [target?.textContent, [...frame.contentDocument.querySelectorAll("h2")].indexOf(target)];
      });
    }""")
    assert len(result) == 2 and all("Same" in item[0] for item in result)
    assert [item[1] for item in result] == [0, 1]
    assert page.evaluate(r"""() => {
      const frame = document.getElementById("preview");
      const lines = document.getElementById("editor").value.split("\n");
      const index = lines.findIndex(line => line.includes("| X"));
      return previewIssueTarget(frame, lines, index)?.tagName;
    }""") == "TABLE"
