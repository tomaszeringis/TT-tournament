# 🎨 UI Development Guidelines

To ensure the codebase remains maintainable for both human developers and AI collaborators, all new UI features must strictly adhere to the following rules.

## 🚫 No Custom CSS Injection
- **DO NOT** use `st.markdown('<style>...</style>', unsafe_allow_html=True)`.
- Avoid any form of manual CSS injection that targets Streamlit's internal DOM.
- This prevents the UI from breaking when Streamlit updates its internal class names or structure.

## ✅ Preferred Component Libraries
Always prefer these libraries for UI elements:

1. **[streamlit-shadcn-ui](https://github.com/nicedouble/streamlit-shadcn-ui)**
    - Use for: Buttons (`ui.button`), Cards (`ui.metric_card`), Badges (`ui.badges`), and other layout components.
    - These components provide a modern, consistent aesthetic that automatically handles theme transitions.

2. **[streamlit-extras](https://arnaudmirabel.github.io/streamlit-extras/)**
    - Use for: Utility enhancements.
    - Use native `st.space("medium")` between major UI sections for consistent layout. (Note: `add_vertical_space` is deprecated in favor of `st.space`).

3. **Native Streamlit Components**
    - Use `st.dataframe` for interactive tables with built-in sorting, column filtering, and responsive design.
    - Use `st.data_editor` for editable tables with full keyboard navigation and accessibility support.
    - Wrap via the helper function `render_interactive_table(df)` in `app/utils.py` for consistent table rendering.

## 🏗️ Native Layouts
If a requirement cannot be met by the libraries above, use native Streamlit layout primitives:
- `st.columns`: For side-by-side elements.
- `st.container`: For logical grouping of elements.
- `st.tabs`: For organized content switching.
- `st.expander`: For collapsible sections.

## 🔔 Notifications
- Use `st.toast()` for non-blocking success/info notifications (e.g., "Match Recorded ✅").
- Use `st.error()` only for critical failures that require user persistence.

## 🧪 Theme Compatibility
- Always ensure components respond correctly to Streamlit's Light/Dark mode.
- Avoid hardcoding color hex codes; use Streamlit's theme-aware defaults where possible.

## 📱 Responsive Design
- Use `use_container_width=True` for tables and charts to adapt to screen size.
- Avoid fixed `height` values on components; use flexible defaults or let Streamlit auto-size.
- For custom HTML components, use CSS variables (`var(--st-color-bg)`, `var(--st-color-text)`) that inherit from Streamlit's theme.
- Test layouts on smaller screens by resizing the browser window.

## 📊 Table Best Practices
- Prefer `st.dataframe` over `st.table` for interactive features (sorting, filtering).
- Use `hide_index=True` to avoid displaying the DataFrame index.
- The `render_interactive_table()` helper provides a consistent interface with:
  - `use_container_width=True` for responsive sizing
  - Built-in column sorting (click headers)
  - Column filtering (click filter icon)
  - Full keyboard navigation support
  - Screen reader accessibility
