# Public demo image (Hugging Face Spaces "Docker" SDK, or any container host). Not tested in this build environment (no Docker available there).
FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user . .
USER user
ENV DEMO_MODE=1 PYTHONUTF8=1 STREAMLIT_BROWSER_GATHER_USAGE_STATS=false STREAMLIT_SERVER_MAX_UPLOAD_SIZE=50
EXPOSE 7860
CMD ["python", "-m", "streamlit", "run", "app_demo.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
