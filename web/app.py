import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import streamlit as st

from core.validator import validate
from core.normalizer import normalize

st.set_page_config(page_title="Thwart", layout="wide")
st.title("Thwart")
st.caption("Paste an openFDA drug label record. See what the pipeline would do with it.")

if "raw" not in st.session_state:
    st.session_state.raw = ""

if st.button("Load example record"):
    sample_path = Path(__file__).parent / "sample.json"
    st.session_state.raw = sample_path.read_text()

raw = st.text_area("Record (JSON)", height=300, key="raw")

if raw:
    try:
        record = json.loads(raw)
    except json.JSONDecodeError as e:
        st.error(f"Not valid JSON: {e}")
        st.stop()

    errors = validate(record)

    left, right = st.columns(2)

    with left:
        st.subheader("Validation")
        if errors:
            st.error(f"REJECTED ({len(errors)} errors)")
            for e in errors:
                st.write(f"- {e}")
            st.stop()
        st.success("ACCEPTED")

    label, sections, skipped = normalize(record)

    with left:
        st.subheader("label row")
        st.table([label])
        if skipped:
            st.subheader(f"Skipped: {len(skipped)} empty sections")
            st.write(", ".join(skipped))

    with right:
        st.subheader(f"label_section rows ({len(sections)})")
        st.dataframe(sections, use_container_width=True)



## cd ~/GitHub/thwart
## source venv/bin/activate
## streamlit run web/app.py 