import base64
import json
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

_ASSETS = Path(__file__).resolve().parents[2] / "assets" / "animations"
_LOTTIE_FILE = _ASSETS / "flow_3.lottie"
_JS_FILE = _ASSETS / "lottie.min.js"


@st.cache_data(show_spinner=False)
def _build_payload(cache_key: tuple, size: int, loop: bool, autoplay: bool):
    try:
        with zipfile.ZipFile(_LOTTIE_FILE, "r") as zf:
            names = zf.namelist()
            json_name = next((n for n in names if n.startswith("a/") and n.endswith(".json")), None)
            if not json_name:
                raise FileNotFoundError("No animation JSON found in dotLottie package")

            raw_json = zf.read(json_name).decode("utf-8")
            animation = json.loads(raw_json)

            image_files = [n for n in names if n.startswith("i/") and not n.endswith("/")]
            image_map = {}
            for img_path in image_files:
                image_map[Path(img_path).name] = base64.b64encode(zf.read(img_path)).decode("ascii")

            if "assets" in animation:
                for asset in animation["assets"]:
                    if isinstance(asset, dict) and asset.get("p") and asset.get("p") in image_map:
                        asset["p"] = f"data:image/png;base64,{image_map[asset['p']]}"
                        asset["u"] = ""
                        asset["e"] = 1

            animation_data = json.dumps(animation, separators=(",", ":"))

        with open(_JS_FILE, "r", encoding="utf-8") as f:
            lottie_js = f.read()

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Loading Animation</title>
<style>
body {{
    margin: 0;
    padding: 0;
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    height: {size}px;
    width: 100%;
    overflow: hidden;
}}
#anim {{
    width: {size}px;
    height: {size}px;
}}
</style>
</head>
<body>
<div id="anim" role="img" aria-label="Loading animation" aria-hidden="true"></div>
<script>
{lottie_js}
</script>
<script>
(function() {{
    try {{
        var container = document.getElementById('anim');
        if (container && typeof lottie !== 'undefined') {{
            var animData = {animation_data};
            lottie.loadAnimation({{
                container: container,
                renderer: 'svg',
                loop: {'true' if loop else 'false'},
                autoplay: {'true' if autoplay else 'false'},
                animationData: animData
            }});
        }}
    }} catch(e) {{
        console.warn('Lottie animation failed to load:', e);
    }}
}})();
</script>
</body>
</html>"""
        return html, None
    except Exception as e:
        return None, str(e)


def render_loading_animation(
    message: str = "Loading...",
    size: int = 160,
    loop: bool = True,
    autoplay: bool = True,
    key: str | None = None,
) -> None:
    if not _LOTTIE_FILE.exists() or not _JS_FILE.exists():
        st.markdown(
            f'<div role="status" aria-live="polite" style="padding:8px 0;">{message}</div>',
            unsafe_allow_html=True,
        )
        return

    cache_key = (
        _LOTTIE_FILE.stat().st_mtime_ns,
        _LOTTIE_FILE.stat().st_size,
        size,
        loop,
        autoplay,
    )
    html, error = _build_payload(cache_key, size, loop, autoplay)

    if html is None:
        st.markdown(
            f'<div role="status" aria-live="polite" style="padding:8px 0;">{message}</div>',
            unsafe_allow_html=True,
        )
        return

    components.html(html, height=size, scrolling=False)
    if message:
        st.caption(message)
