"""Router. Simple mode is the default screen; Advanced mode (Settings, or ?advanced=1) holds everything else."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import streamlit as st

st.set_page_config(page_title="Customer Value Review", layout="wide")
S = st.session_state
import providers

if "advanced" not in S:                                  # off by default, remembered for the session
    S.advanced = st.query_params.get("advanced", "") in ("1", "true", "yes")


def _sync():
    S.advanced = bool(S.get("adv_widget"))


S["adv_widget"] = S.advanced                              # keep widget in step when Simple mode's button flips it
with st.sidebar:
    st.markdown("### Settings")
    st.toggle("Advanced mode", key="adv_widget", on_change=_sync,
              help="Shows the full set of tools: data mapping, portfolio, customer pages, analyst, meeting pack. Your work is kept when you switch.")
    if providers.demo_mode():
        st.caption("Public demo: synthetic sample data only, uploads and AI are switched off. Please do not use real customer data here.")

if S.advanced:
    import advanced_ui
    advanced_ui.render_advanced()
else:
    import simple_ui
    simple_ui.render_simple()
