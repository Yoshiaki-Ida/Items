from __future__ import annotations

import pytest

from manual_tool.lint_engine import lint_text


@pytest.mark.parametrize(
    "heading",
    ["# 概要", "#1.概要", "# 1. 概要", "# １．概要", "# １． 概要", "# 1.1 概要"],
)
def test_required_section_accepts_numbered_heading(heading):
    issues = lint_text(
        heading,
        {"required_sections": [{"level": 1, "title": "概要"}]},
    )

    assert not [issue for issue in issues if issue.rule == "required-section"]