# Public demo: deploy in about 10 minutes

The public demo uses **`app_demo.py`**. It forces demo mode: synthetic sample data only, uploads switched off, AI switched off, no API key needed or used.
A judge opens the link, presses **"Use the sample data"**, and gets one editable PowerPoint per customer (3), or all of them as a ZIP.
Nothing is stored. Do not point a public deployment at `app.py` (that one accepts uploads).

## Option A: Streamlit Community Cloud (recommended)
1. Put the contents of this folder at the **root** of a GitHub repository (the folder that contains `app_demo.py`, not its parent).
   ```
   cd lindstrom-review
   git init && git add . && git commit -m "Customer Value Review"
   git branch -M main && git remote add origin https://github.com/<you>/<repo>.git && git push -u origin main
   ```
   The repo can be public. It holds no secrets (`.gitignore` excludes `secrets.toml`).
2. Go to https://share.streamlit.io, sign in with GitHub, press **Create app → Deploy a public app from GitHub**.
3. Repository: `<you>/<repo>`, Branch: `main`, **Main file path: `app_demo.py`**.
4. Open **Advanced settings** and choose **Python 3.12** (or 3.13). Leave Secrets empty.
5. Press **Deploy**. The first start installs the packages (a few minutes). Copy the `https://<name>.streamlit.app` link.
6. **Test it cold**, in a private window: press "Use the sample data" and wait for the decks (expect up to a minute on a shared server), download one deck, open it in PowerPoint.
   If the app ever fails to install, change `requirements.txt` to the contents of `requirements-tested.txt` and redeploy.

Community Cloud puts an app to sleep after a few days without visitors; open the link shortly before the deadline and before judging to wake it.

## Option B: Hugging Face Spaces (Docker)
1. https://huggingface.co/new-space → SDK **Docker** → Blank, visibility Public.
2. Upload every file in this folder to the Space (or `git push` to it). The included `Dockerfile` runs `app_demo.py` on port 7860.
   Add this to the top of the Space's `README.md`:
   ```
   ---
   title: Customer Value Review
   sdk: docker
   app_port: 7860
   ---
   ```
3. Wait for "Running", then open the Space link. (The Dockerfile was not built in this environment because Docker is not available there; Option A was the tested route.)

## Notes
- Without `DEMO_MODE` (that is, `app.py`) the app accepts uploads and, if an API key is set, can use an LLM. Keep that for local use.
- If you later want AI on a private deployment, set `ANTHROPIC_API_KEY` in the platform's **secrets**, never in the repository.
- The synthetic sample data is not Lindström data. Say so in the submission text.
