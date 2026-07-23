"""
Tests that every Streamlit page declares a LitIT-branded page title.

Scans the page modules under ``tournament_platform/app/pages`` (and the entry
point ``main.py``) for ``st.set_page_config(...)`` calls and asserts the
``page_title`` argument is branded with the LitIT name.
"""

import ast
import os

import pytest

APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "tournament_platform",
    "app",
)

PAGE_FILES = [
    os.path.join(APP_DIR, "main.py"),
    *[
        os.path.join(APP_DIR, "pages", f)
        for f in sorted(os.listdir(os.path.join(APP_DIR, "pages")))
        if f.endswith(".py") and f != "__init__.py"
    ],
]

PUBLIC_BYPASS_PAGES = {
    "public_board_readonly.py",
    "public_registration.py",
}


def _page_titles_from_source(path):
    """Return list of (filename, page_title_ast_node) for set_page_config calls."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)

    titles = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match st.set_page_config (Attribute) or set_page_config (Name)
        is_target = (
            isinstance(func, ast.Attribute) and func.attr == "set_page_config"
        ) or (isinstance(func, ast.Name) and func.id == "set_page_config")
        if not is_target:
            continue
        for kw in node.keywords:
            if kw.arg == "page_title":
                titles.append(kw.value)
    return titles


def _is_branded(node):
    """A page_title is branded if it is a literal starting with LIT_IT or an
    f-string whose first segment resolves to the BRAND name token."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.startswith("LIT_IT")
    if isinstance(node, ast.JoinedStr):
        # Inspect the leading value part of the f-string.
        if not node.values:
            return False
        first = node.values[0]
        snippet = ast.unparse(first)
        # Either the literal prefix already says LIT_IT, or it interpolates
        # the brand name token (BRAND name / 'name').
        return snippet.startswith("LIT_IT") or (
            "BRAND" in snippet and "name" in snippet
        )
    return False


@pytest.mark.parametrize("path", PAGE_FILES, ids=lambda p: os.path.basename(p))
def test_page_titles_are_branded(path):
    basename = os.path.basename(path)
    if basename in PUBLIC_BYPASS_PAGES:
        pytest.skip(f"{basename} is a public bypass page and must not call set_page_config")
    if not os.path.exists(path):
        pytest.skip(f"{path} not present")
    titles = _page_titles_from_source(path)
    assert titles, f"No set_page_config(page_title=...) found in {basename}"
    for title_node in titles:
        assert _is_branded(title_node), (
            f"page_title in {basename} is not branded with LIT_IT: "
            f"{ast.unparse(title_node)}"
        )
