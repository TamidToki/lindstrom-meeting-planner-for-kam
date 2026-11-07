#!/usr/bin/env bash
# One-step start for macOS and Linux. Creates a private Python environment on first run.
cd "$(dirname "$0")" || exit 1
echo; echo "  Meeting Planner"; echo "  ---------------"
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "  Python 3 is needed once (free). Opening the download page."
  (command -v open >/dev/null && open https://www.python.org/downloads/) || (command -v xdg-open >/dev/null && xdg-open https://www.python.org/downloads/)
  read -r -p "  Install it, then run this again. Press Enter to close. " _; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "  First start: setting things up. This takes a few minutes, once only."
  "$PY" -m venv .venv || { echo "  Could not create the environment."; read -r -p "  Press Enter to close. " _; exit 1; }
fi
if [ ! -f .venv/.installed ]; then
  .venv/bin/python -m pip install --quiet --disable-pip-version-check --upgrade pip
  .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt || { echo "  Setup failed. Check your internet connection and try again."; read -r -p "  Press Enter to close. " _; exit 1; }
  echo ok > .venv/.installed
fi
mkdir -p "$HOME/.streamlit"
[ -f "$HOME/.streamlit/credentials.toml" ] || printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
echo; echo "  Starting. Your browser opens in a moment."; echo "  Keep this window open while you work. Close it to stop."; echo
EXTRA=""; [ -n "$MP_NO_BROWSER" ] && EXTRA="--server.headless true"
exec .venv/bin/python -m streamlit run app.py $EXTRA
