# Content Insight Hub — Render-ready

Internal Content Insight app:
- Text -> insight
- Image -> OCR/visual understanding -> insight
- Video -> ffmpeg audio transcription + sampled visual frames -> insight
- PostgreSQL-backed Insight Library
- Docker deployment on Render

## Recommended deploy: Render Blueprint

This repository includes:
- `Dockerfile` — installs Python dependencies + ffmpeg
- `render.yaml` — creates the web service and Render Postgres
- `/health` — Render health check endpoint

### Deploy steps

1. Upload/commit all files in this repository to GitHub.
2. Sign in to Render.
3. New -> Blueprint.
4. Connect the GitHub repository containing this app.
5. Render reads `render.yaml` and proposes:
   - `content-insight-hub` web service
   - `content-insight-db` PostgreSQL database
6. Enter the required `OPENAI_API_KEY` secret when prompted.
7. Apply/Deploy the Blueprint.
8. After deployment, open the generated `*.onrender.com` URL.

Do not commit your OpenAI API key to GitHub.

## Local run

Without `DATABASE_URL`, the app automatically falls back to local SQLite.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="..."
python app.py
```

Video analysis needs ffmpeg installed locally.
