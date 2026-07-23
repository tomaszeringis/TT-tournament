"""
Tests for the public board read-only renderer.
"""

import inspect

import tournament_platform.app.pages.public_board_readonly as pbr


class TestPublicBoardReadonly:
    def test_render_function_exists(self):
        assert callable(pbr.render_public_board_readonly)

    def test_no_set_page_config_in_render_function(self):
        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "set_page_config(" not in source

    def test_no_set_page_config_at_module_top_level(self):
        src = inspect.getsource(pbr)
        # set_page_config should only appear inside function bodies, not at top level.
        # A simple check: the module-level source lines should not contain it.
        module_lines = src.split("\n")
        top_level_uses = [
            line.strip()
            for line in module_lines
            if "set_page_config(" in line and not line.strip().startswith("#")
        ]
        # There should be no top-level occurrences outside function/class defs
        for line in top_level_uses:
            # Allow if it's inside a def/class body by checking indentation depth
            stripped = line.lstrip()
            if stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("@"):
                continue
            # If we reach here, it's an unindented or function-header line — should not exist
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
        source = inspect.getsource(pbr.render_public_board_readonly)
        for label in forbidden:
            assert label not in source, f"Forbidden mutation label found: {label}"


class TestPublicBoardLanePolish:
    def test_called_status_passed_to_coming_up_card(self):
        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "call_status=" in source

    def test_waiting_for_previous_match_in_source(self):
        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "Waiting for previous match" in source

    def test_game_scores_passed_to_cards(self):
        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "game_scores" in source
        assert "render_public_result_row" in source

    def test_pairing_expander_in_source(self):
        source = inspect.getsource(pbr.render_public_board_readonly)
        assert "render_pairing_expander" in source
