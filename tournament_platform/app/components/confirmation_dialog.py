"""
Confirmation Dialog Component for high-risk writes.

Provides a reusable confirmation layer that integrates with the operator
command parser ``requires_confirmation`` flag.
"""

from typing import Optional, Callable, Any

import streamlit as st


class ConfirmationDialog:
    """Reusable confirmation dialog for high-risk operator actions."""

    def __init__(self, key_prefix: str = "confirm"):
        self.key_prefix = key_prefix
        if f"{key_prefix}_pending" not in st.session_state:
            st.session_state[f"{key_prefix}_pending"] = None

    def confirm(
        self,
        action_label: str,
        description: str = "",
        on_confirm: Optional[Callable[[], Any]] = None,
        confirm_button: str = "✅ Confirm",
        cancel_button: str = "Cancel",
    ) -> bool:
        """
        Render a confirmation dialog.

        Returns True if the action was confirmed and executed.
        """
        pending = st.session_state.get(f"{self.key_prefix}_pending")
        if not pending:
            if st.button(action_label, key=f"{self.key_prefix}_{action_label}_trigger"):
                st.session_state[f"{self.key_prefix}_pending"] = {
                    "label": action_label,
                    "description": description,
                    "on_confirm": on_confirm,
                }
                st.rerun()
            return False

        st.warning(f"Please confirm: {pending['label']}")
        if pending.get("description"):
            st.caption(pending["description"])

        col_confirm, col_cancel = st.columns([1, 1])
        with col_confirm:
            if st.button(confirm_button, key=f"{self.key_prefix}_do_confirm", type="primary"):
                callback = pending.get("on_confirm")
                if callback:
                    try:
                        callback()
                    except Exception as e:
                        st.error(f"Action failed: {e}")
                        st.session_state[f"{self.key_prefix}_pending"] = None
                        return False
                st.session_state[f"{self.key_prefix}_pending"] = None
                st.rerun()
                return True

        with col_cancel:
            if st.button(cancel_button, key=f"{self.key_prefix}_cancel"):
                st.session_state[f"{self.key_prefix}_pending"] = None
                st.rerun()

        return False
