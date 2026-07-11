"""
Tests for the LitIT brand asset placeholders.

Verifies that the ``assets/brand`` directory exists and documents its
placeholder status (no official LitIT logo assets have been added yet).
"""

import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
BRAND_DIR = os.path.join(REPO_ROOT, "assets", "brand")

PLACEHOLDER_FILES = [
    "litit-logo-light.svg",
    "litit-logo-dark.svg",
    "litit-favicon.svg",
]


def test_brand_assets_directory_exists():
    assert os.path.isdir(BRAND_DIR), (
        "assets/brand directory is missing; brand placeholders were not created"
    )


def test_brand_placeholder_files_exist():
    missing = [
        f for f in PLACEHOLDER_FILES
        if not os.path.exists(os.path.join(BRAND_DIR, f))
    ]
    # Either the three placeholder SVGs exist, or the README documents the
    # placeholder status (acceptable per brand misuse rules).
    readme = os.path.join(BRAND_DIR, "README.md")
    assert not missing or os.path.exists(readme), (
        f"Missing brand placeholder files: {missing} and no README documenting "
        "the placeholder status was found."
    )


def test_brand_readme_documents_placeholder_status():
    readme = os.path.join(BRAND_DIR, "README.md")
    assert os.path.exists(readme), "assets/brand/README.md documenting placeholders is missing"
    with open(readme, encoding="utf-8") as fh:
        content = fh.read().lower()
    assert "placeholder" in content, "README must document that assets are placeholders"
    assert "official" in content, "README must note that official assets are not yet added"
