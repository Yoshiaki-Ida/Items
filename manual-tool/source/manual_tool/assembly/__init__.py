"""Deterministic manual composition and build APIs."""

from .builder import BuildResult, build_manual
from .project import HtmlSource, discover_html
from .schema import ManualDefinition, ManualNode, load_manual, save_manual
from .validator import ValidationIssue, validate_manual

__all__ = [
    "BuildResult",
    "HtmlSource",
    "ManualDefinition",
    "ManualNode",
    "ValidationIssue",
    "build_manual",
    "discover_html",
    "load_manual",
    "save_manual",
    "validate_manual",
]
