"""
Tests for the public registration page.
"""

import inspect

import tournament_platform.app.pages.public_registration as pr


class TestPublicRegistration:
    def test_render_function_exists(self):
        assert callable(pr.render_public_registration)

    def test_no_set_page_config_in_render_function(self):
        source = inspect.getsource(pr.render_public_registration)
        assert "set_page_config(" not in source

    def test_no_set_page_config_at_module_top_level(self):
        src = inspect.getsource(pr)
        module_lines = src.split("\n")
        top_level_uses = [
            line.strip()
            for line in module_lines
            if "set_page_config(" in line and not line.strip().startswith("#")
        ]
        for line in top_level_uses:
            stripped = line.lstrip()
            if stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("@"):
                continue
            raise AssertionError(f"Unexpected module-level set_page_config: {line}")

    def test_no_mutation_labels_in_source(self):
        forbidden = [
            "Submit Result",
            "Delete",
            "Reset",
            "Voice Scoring",
            "Complete Match",
            "Call Match",
            "Post to Teams",
        ]
        source = inspect.getsource(pr.render_public_registration)
        for label in forbidden:
            assert label not in source, f"Forbidden mutation label found: {label}"

    def test_no_admin_controls_in_source(self):
        forbidden = [
            "st.secrets",
            "environ",
            "API base",
            "Diagnostics",
            "st.cache_resource",
        ]
        source = inspect.getsource(pr.render_public_registration)
        lower = source.lower()
        for label in forbidden:
            assert label not in lower, f"Forbidden admin/danger term found: {label}"


class TestPublicBoardRegistrationQr:
    def test_public_board_contains_register_link_pattern(self):
        import tournament_platform.app.pages.public_board as pb

        source = inspect.getsource(pb.render_public_board)
        assert "public=1&register=1" in source

    def test_public_board_readonly_contains_register_link_pattern(self):
        import tournament_platform.app.pages.public_board_readonly as pbr

        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "public=1&register=1" in source

    def test_public_board_uses_register_to_play_label(self):
        import tournament_platform.app.pages.public_board as pb

        source = inspect.getsource(pb.render_public_board)
        assert "Register to play" in source
        assert "Check In" in source

    def test_public_board_readonly_uses_register_to_play_label(self):
        import tournament_platform.app.pages.public_board_readonly as pbr

        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "Register to play" in source
        assert "Check In" in source

    def test_public_board_does_not_render_registration_form(self):
        import tournament_platform.app.pages.public_board as pb

        source = inspect.getsource(pb.render_public_board)
        forbidden = [
            "Submit Registration",
            "Approve Player",
            "Merge Duplicate",
            "render_public_registration",
        ]
        for label in forbidden:
            assert label not in source, f"Public Board must not render registration form: {label}"

    def test_public_board_readonly_does_not_render_registration_form(self):
        import tournament_platform.app.pages.public_board_readonly as pbr

        source = inspect.getsource(pbr.render_public_board_readonly)
        forbidden = [
            "Submit Registration",
            "Approve Player",
            "Merge Duplicate",
            "render_public_registration",
        ]
        for label in forbidden:
            assert label not in source, f"Public Board must not render registration form: {label}"

    def test_public_board_contains_pairing_expander(self):
        import tournament_platform.app.pages.public_board as pb

        source = inspect.getsource(pb.render_public_board)
        assert "render_pairing_expander" in source
