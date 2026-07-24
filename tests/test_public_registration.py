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
        assert "get_registration_link" in source

    def test_public_board_readonly_contains_register_link_pattern(self):
        import tournament_platform.app.pages.public_board_readonly as pbr

        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "get_registration_link" in source

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

    def test_public_board_uses_render_qr_block_helper(self):
        import tournament_platform.app.pages.public_board as pb

        source = inspect.getsource(pb.render_public_board)
        assert "_render_public_qr_block" in source

    def test_public_board_has_distinct_qr_captions(self):
        import tournament_platform.app.pages.public_board as pb

        source = inspect.getsource(pb.render_public_board)
        assert "Scan to follow scores" in source
        assert "Scan to register" in source
        assert "Scan to check in" in source

    def test_public_board_uses_conditional_columns_for_registration(self):
        import tournament_platform.app.pages.public_board as pb

        source = inspect.getsource(pb.render_public_board)
        assert "ENABLE_SELF_REGISTRATION" in source
        assert "st.columns(2)" in source

    def test_public_board_shows_registration_closed_message(self):
        import tournament_platform.app.pages.public_board as pb

        source = inspect.getsource(pb.render_public_board)
        assert "Registration is closed" in source

    def test_public_board_no_admin_controls_in_source(self):
        import tournament_platform.app.pages.public_board as pb

        source = inspect.getsource(pb.render_public_board)
        forbidden = [
            "approve_player",
            "reject_player",
            "Approve Player",
            "Reject Player",
            "merge_duplicate",
            "Merge Duplicate",
            "add_player",
            "Add Player",
            "generate_bracket",
            "Generate Bracket",
            "submit_result",
            "Submit Result",
            "st.secrets",
            "environ",
            "API base",
            "Diagnostics",
            "st.cache_resource",
        ]
        lower = source.lower()
        for label in forbidden:
            assert label not in lower, f"Forbidden admin/mutation term found in public_board: {label}"

    def test_public_board_readonly_uses_render_qr_block_helper(self):
        import tournament_platform.app.pages.public_board_readonly as pbr

        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "_render_public_qr_block" in source

    def test_public_board_readonly_has_distinct_qr_captions(self):
        import tournament_platform.app.pages.public_board_readonly as pbr

        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "Scan to follow scores" in source
        assert "Scan to register" in source
        assert "Scan to check in" in source

    def test_public_board_readonly_uses_conditional_columns_for_registration(self):
        import tournament_platform.app.pages.public_board_readonly as pbr

        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "ENABLE_SELF_REGISTRATION" in source
        assert "st.columns(2)" in source

    def test_public_board_readonly_shows_registration_closed_message(self):
        import tournament_platform.app.pages.public_board_readonly as pbr

        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "Registration is closed" in source

    def test_public_board_readonly_no_admin_controls_in_source(self):
        import tournament_platform.app.pages.public_board_readonly as pbr

        source = inspect.getsource(pbr.render_public_board_readonly)
        forbidden = [
            "approve_player",
            "reject_player",
            "Approve Player",
            "Reject Player",
            "merge_duplicate",
            "Merge Duplicate",
            "add_player",
            "Add Player",
            "generate_bracket",
            "Generate Bracket",
            "submit_result",
            "Submit Result",
            "st.secrets",
            "environ",
            "API base",
            "Diagnostics",
            "st.cache_resource",
        ]
        lower = source.lower()
        for label in forbidden:
            assert label not in lower, f"Forbidden admin/mutation term found in public_board_readonly: {label}"
