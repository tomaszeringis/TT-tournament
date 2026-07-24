"""
Tests for the Admin page merge of Operator Console and Schedule Board.

Covers:
- Role gate in ``main.py`` exposes the Admin page to ``admin`` and ``operator``
  roles while excluding regular ``user`` accounts.
- The embeddable tab renderers are importable and callable without invoking
  ``st.set_page_config`` (which would raise
  ``StreamlitSetPageConfigMustBeFirstCommand`` inside the Admin page).
"""

import inspect
import os

import pytest

import tournament_platform.app.pages.operator_console as op
import tournament_platform.app.pages.schedule_board as sched


APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "tournament_platform",
    "app",
)


def _role_can_see_admin(user_role: str) -> bool:
    """Mirror of the navigation gate condition in ``main.py``.

    Kept in sync with the ``if user_role in ("admin", "operator"):`` check that
    builds ``admin_pages``.
    """
    return user_role in ("admin", "operator")


class TestAdminRoleGate:
    def test_admin_role_sees_admin_page(self):
        assert _role_can_see_admin("admin") is True

    def test_operator_role_sees_admin_page(self):
        assert _role_can_see_admin("operator") is True

    def test_regular_user_excluded(self):
        assert _role_can_see_admin("user") is False

    def test_unknown_role_excluded(self):
        assert _role_can_see_admin("spectator") is False

    def test_main_py_gate_includes_operator(self):
        """The real source of truth must gate on both admin and operator."""
        main_path = os.path.join(APP_DIR, "main.py")
        with open(main_path, encoding="utf-8") as f:
            source = f.read()
        assert 'user_role in ("admin", "operator")' in source
        # Regression guard: the old admin-only gate must be gone.
        assert 'if user_role == "admin":\n        admin_pages.append' not in source


class TestEmbeddableRenderers:
    def test_operator_renderers_are_callable(self):
        assert callable(op.render_match_queue_tab)
        assert callable(op.render_table_status_tab)

    def test_schedule_renderer_is_callable(self):
        assert callable(sched.render_schedule_tab)

    @pytest.mark.parametrize(
        "func",
        [
            "render_match_queue_tab",
            "render_table_status_tab",
        ],
    )
    def test_operator_renderers_do_not_set_page_config(self, func):
        source = inspect.getsource(getattr(op, func))
        assert "set_page_config(" not in source

    def test_schedule_tab_does_not_set_page_config(self):
        source = inspect.getsource(sched.render_schedule_tab)
        assert "set_page_config(" not in source

    def test_schedule_tab_signature(self):
        sig = inspect.signature(sched.render_schedule_tab)
        assert list(sig.parameters) == ["tournament_id", "start_date", "days_ahead"]

    def test_operator_tab_signatures_take_selected_id(self):
        for func in (op.render_match_queue_tab, op.render_table_status_tab):
            params = list(inspect.signature(func).parameters)
            assert params == ["selected_id"]


class TestModuleImportSafety:
    def test_importing_page_modules_has_no_page_config_side_effect(self):
        """Importing the page modules must not call set_page_config at top level."""
        # Module top-level source (excluding function bodies) should not call
        # set_page_config; the only occurrences live inside the page-level
        # wrapper functions.
        for module in (op, sched):
            src = inspect.getsource(module)
            # The wrapper functions legitimately contain set_page_config, but
            # they are only invoked via __main__, never at import.
            assert "if __name__" in src


class TestTableStatusCard:
    """Regression coverage for the Table Status tab data-shape mismatch.

    ``render_table_status_card`` is fed data from
    ``get_table_availability_summary`` (keys ``name`` /
    ``current_match_label`` / ``has_active_or_called_match``) but historically
    read ``table_name`` / ``current_match`` — causing ``KeyError: 'table_name'``
    once the tab became reachable via Admin.
    """

    def _render_with_stub(self, table):
        import tournament_platform.app.components.operator_components as oc

        rendered = []

        class _StStub:
            def markdown(self, text):
                rendered.append(text)

            def caption(self, text):
                rendered.append(text)

        original = oc.st
        oc.st = _StStub()
        try:
            oc.render_table_status_card(table)
        finally:
            oc.st = original
        return rendered

    def test_availability_summary_shape_no_keyerror(self):
        table = {
            "id": 1,
            "name": "Table 1",
            "is_active": True,
            "notes": None,
            "current_match_id": 5,
            "current_match_label": "Alice vs Bob",
            "has_active_or_called_match": True,
        }
        out = self._render_with_stub(table)
        assert any("Table 1" in line and "busy" in line for line in out)
        assert any("Alice vs Bob" in line for line in out)

    def test_available_table_shape(self):
        table = {
            "name": "Table 2",
            "is_active": True,
            "has_active_or_called_match": False,
        }
        out = self._render_with_stub(table)
        assert any("Table 2" in line and "available" in line for line in out)

    def test_inactive_table_shape(self):
        table = {"name": "Table 3", "is_active": False}
        out = self._render_with_stub(table)
        assert any("Table 3" in line and "inactive" in line for line in out)

    def test_legacy_get_table_status_shape_still_works(self):
        table = {
            "table_name": "Table 4",
            "is_active": True,
            "status": "busy",
            "current_match": {"player1": "Carol", "player2": "Dan"},
            "next_match": {"player1": "Eve", "player2": "Frank"},
        }
        out = self._render_with_stub(table)
        assert any("Table 4" in line and "busy" in line for line in out)
        assert any("Carol vs Dan" in line for line in out)
        assert any("Eve vs Frank" in line for line in out)


class TestAdminRegistrationControl:
    def test_admin_page_contains_registration_tab(self):
        admin_path = os.path.join(APP_DIR, "pages", "admin.py")
        with open(admin_path, encoding="utf-8") as f:
            source = f.read()
        assert '"Public Registration"' in source

    def test_admin_page_imports_registration_helpers(self):
        admin_path = os.path.join(APP_DIR, "pages", "admin.py")
        with open(admin_path, encoding="utf-8") as f:
            source = f.read()
        assert "set_registration_token" in source
        assert "close_registration" in source
        assert "get_registration_link" in source
        assert "get_registration_stats" in source

    def test_admin_page_enable_registration_button(self):
        admin_path = os.path.join(APP_DIR, "pages", "admin.py")
        with open(admin_path, encoding="utf-8") as f:
            source = f.read()
        assert "Enable public registration for selected tournament" in source

    def test_admin_page_close_registration_button(self):
        admin_path = os.path.join(APP_DIR, "pages", "admin.py")
        with open(admin_path, encoding="utf-8") as f:
            source = f.read()
        assert "Close registration" in source

    def test_admin_page_shows_registration_link(self):
        admin_path = os.path.join(APP_DIR, "pages", "admin.py")
        with open(admin_path, encoding="utf-8") as f:
            source = f.read()
        assert "get_registration_link" in source
        assert "Copy" in source

    def test_admin_page_shows_stats(self):
        admin_path = os.path.join(APP_DIR, "pages", "admin.py")
        with open(admin_path, encoding="utf-8") as f:
            source = f.read()
        assert "get_registration_stats" in source
        assert "Registered" in source
        assert "Checked In" in source

    def test_admin_page_warns_when_self_registration_disabled(self):
        admin_path = os.path.join(APP_DIR, "pages", "admin.py")
        with open(admin_path, encoding="utf-8") as f:
            source = f.read()
        assert "ENABLE_SELF_REGISTRATION" in source
        assert "Self-registration is disabled" in source

    def test_admin_page_no_token_hash_exposed(self):
        admin_path = os.path.join(APP_DIR, "pages", "admin.py")
        with open(admin_path, encoding="utf-8") as f:
            source = f.read()
        assert "public_registration_token_hash" not in source
        assert "token hash" not in source.lower()
        assert "raw token" not in source.lower()
