"""Run: streamlit run ui/dashboard.py -- --telemetry telemetry.json"""
import argparse
import json
from pathlib import Path
import time
import streamlit as st


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--telemetry", default="telemetry.json")
    args = parser.parse_args()
    path = Path(args.telemetry)
    st.set_page_config(page_title="Spatial Controller Diagnostics", layout="wide")
    st.title("Spatial Controller Diagnostics")
    st.caption("File snapshots refresh once per second; dashboard does not run inference.")

    @st.fragment(run_every=1)
    def panel():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            st.info(f"Waiting for telemetry: {exc}")
            return
        age = time.time() - data.get("updated_unix", 0)
        if age > 2 or not data.get("running", False):
            st.warning(f"Controller stopped or snapshot stale ({age:.1f}s old)")
        cols = st.columns(3)
        cols[0].metric("Processed FPS", f"{data.get('fps', 0):.1f}")
        cols[1].metric("Read to submit p95", f"{data.get('latency_p95_ms', 0):.1f} ms")
        cols[2].metric("Dropped captures", data.get("capture_replacements", 0))
        st.json(data)

    panel()


if __name__ == "__main__":
    main()
