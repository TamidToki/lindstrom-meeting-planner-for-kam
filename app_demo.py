"""Entry point for a PUBLIC demo (Streamlit Community Cloud, Hugging Face Spaces, any shared server).
It forces demo mode before the app starts: synthetic sample data only, uploads off, AI off, no API key used. Point the host at this file."""
import os
import runpy
os.environ["DEMO_MODE"] = "1"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"), run_name="__main__")
