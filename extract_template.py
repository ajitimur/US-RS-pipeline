"""
extract_template.py
===================
Split docs/index.html into template parts used by build_dashboard.py.
"""

from __future__ import annotations

import os
import sys


def extract(source_path: str) -> None:
    with open(source_path, encoding="utf-8") as f:
        html = f.read()

    marker = "const EMBEDDED ="
    start = html.find(marker)
    if start == -1:
        raise ValueError(f"Marker `{marker}` not found in {source_path}")
    data_end = html.find(";\n", start) + 2
    script_end = html.rfind("</script>")
    if data_end < 2 or script_end == -1:
        raise ValueError("Could not detect template boundaries.")

    tmpl_a = html[:start]
    tmpl_b = html[data_end:script_end]
    tmpl_c = html[script_end:]

    here = os.path.dirname(os.path.abspath(__file__))
    outputs = {
        "dashboard_template_a.html": tmpl_a,
        "dashboard_template_b.js": tmpl_b,
        "dashboard_template_c.html": tmpl_c,
    }
    for name, content in outputs.items():
        path = os.path.join(here, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Wrote {name} ({len(content):,} bytes)")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join("docs", "index.html")
    extract(src)
