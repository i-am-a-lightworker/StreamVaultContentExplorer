from pathlib import Path
import shutil
from datetime import datetime

TARGET = Path("streamvault_dashboard.py")

if not TARGET.exists():
    raise SystemExit("streamvault_dashboard.py was not found in this folder.")

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = TARGET.with_name(f"streamvault_dashboard_backup_{stamp}.py")
shutil.copy2(TARGET, backup)

text = TARGET.read_text(encoding="utf-8")

# Add Plotly imports once.
if "import plotly.express as px" not in text:
    anchor = "import pandas as pd\nimport streamlit as st\n"
    replacement = (
        "import pandas as pd\n"
        "import plotly.express as px\n"
        "import plotly.graph_objects as go\n"
        "import streamlit as st\n"
    )
    if anchor not in text:
        raise SystemExit("Could not find the pandas/Streamlit import block.")
    text = text.replace(anchor, replacement, 1)

# Insert reusable visual functions before choose_catalog.
visual_marker = "\ndef choose_catalog() -> tuple[pd.DataFrame | None, str | None]:\n"

visual_code = r