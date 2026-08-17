# Voice Scorekeeper — Widget Key Inventory

Source file: `tournament_platform/app/pages/voice_scorekeeper.py`
Total widgets: 60+

## Page Header & Getting Started
| Widget key | Widget type | Line |
|------------|-------------|------|
| (rendered by `render_page_header`) | — | — |
| (rendered by `render_tour`) | — | — |

## Commentary
| Widget key | Widget type | Line |
|------------|-------------|------|
| (rendered by `render_commentary_settings`) | — | — |
| (rendered by `render_commentary_log`) | — | — |
| (rendered by `render_commentary_debug`) | — | — |

## Match Selection
| Widget key | Widget type | Line |
|------------|-------------|------|
| (rendered by `render_active_match_selector`) | — | — |
| (rendered by `render_selected_match_summary`) | — | — |

## Player Selection
| Widget key | Widget type | Line |
|------------|-------------|------|
| `player_a_select` | selectbox | 5748 |
| `player_b_select` | selectbox | 5778 |

## Live Scoreboard
| Widget key | Widget type | Line |
|------------|-------------|------|
| `setup_points` | selectbox | 5826 |
| `setup_games_to_win` | selectbox | 5829 |
| `setup_firstserver` | selectbox | 5832 |
| `apply_format` | button | 5833 |
| `add_point_a` | button | 5846 |
| `sub_point_a` | button | 5867 |
| `undo_point_center` | button | 5912 |
| `undo_game_center` | button | 5924 |
| `reset_game_center` | button | 5938 |
| `reset_match_center` | button | 5949 |
| `add_point_b` | button | 5995 |
| `sub_point_b` | button | 6016 |
| `next_game_btn` | button | 6120 |
| `submit_result_btn` | button | 6167 |
| `rematch_btn` | button | 6220 |
| `new_match_btn` | button | 6230 |

## Quick Voice Stats
| Widget key | Widget type | Line |
|------------|-------------|------|
| (no extra widget keys; conditional render) | — | — |

## Round/Match Winner
| Widget key | Widget type | Line |
|------------|-------------|------|
| (no extra widget keys; conditional render) | — | — |

## Voice Settings (inside `render_voice_sections`)
| Widget key | Widget type | Line |
|------------|-------------|------|
| (toggle `voice_scoring_enabled` no explicit key) | toggle | 4468 |
| (segmented `quick_voice_mode` no explicit key) | segmented_control | 4475 |
| (toggle `tt_sounds_enabled` no explicit key) | toggle | 4512 |
| `noise_recommend_btn` | button | 4548 |
| `speaker_select` | selectbox | 5973 |

## Voice Input
| Widget key | Widget type | Line |
|------------|-------------|------|
| `voice_push_to_talk_input` | audio_input | 5278 |
| `push_to_talk_btn` | button | 5325 |
| `continuous_mode_btn` | button | 5329 |

## Dataset
| Widget key | Widget type | Line |
|------------|-------------|------|
| (rendered by `_render_dataset_panel`) | — | — |

## Analytics
| Widget key | Widget type | Line |
|------------|-------------|------|
| `match_analytics_select` | selectbox | 5448 |
| `generate_ai_summary_btn` | button | 5506 |
| `export_report_btn` | button | 5514 |
| `download_match_report` | download_button | 5534 |
| `recap_tone_select` | selectbox | 5593 |
| `regenerate_recap` | button | 5609 |
| `post_recap_to_teams` | button | 5613 |
| `copy_recap_message` | button | 5629 |

## Commentaries / Observability
| Widget key | Widget type | Line |
|------------|-------------|------|
| `export_audit_log` | button | 5216 |
| `download_audit` | download_button | 5222 |
| `clear_audit_log` | button | 5229 |
| `clear_voice_log` | button | 5069 |

## ASR Diagnostics
| Widget key | Widget type | Line |
|------------|-------------|------|
| `asr_test_imports` | button | 5039 |
| `asr_test_load` | button | 5042 |
| `asr_refresh` | button | 5049 |

## Debug Voice Pipeline
| Widget key | Widget type | Line |
|------------|-------------|------|
| `voice_debug_transcript` | text_input | 5157 |
| `voice_debug_process_btn` | button | 5162 |

## Announcements
| Widget key | Widget type | Line |
|------------|-------------|------|
| `voice_announcements_toggle` | toggle | 5642 |
