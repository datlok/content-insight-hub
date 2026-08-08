
import os, json, base64, sqlite3, subprocess, tempfile, mimetypes, shutil, re
from pathlib import Path
from datetime import datetime
import requests
from flask import Flask, render_template, request, jsonify

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "insights.db"
UPLOAD_DIR = APP_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-5-mini")
VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", TEXT_MODEL)
TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_name TEXT,
        raw_text TEXT,
        summary TEXT,
        core_insight TEXT,
        audience TEXT,
        tension TEXT,
        content_angles TEXT,
        hooks TEXT,
        tags TEXT,
        status TEXT DEFAULT 'New'
    )
    """)
    conn.commit()
    conn.close()

def response_text(data):
    if isinstance(data, dict) and data.get("output_text"):
        return data["output_text"]
    parts = []
    for item in data.get("output", []) if isinstance(data, dict) else []:
        for c in item.get("content", []):
            if c.get("type") in ("output_text", "text") and c.get("text"):
                parts.append(c["text"])
    return "\n".join(parts)

def openai_response(content, model=None):
    if not OPENAI_API_KEY:
        raise RuntimeError("Chưa cấu hình OPENAI_API_KEY.")
    payload = {
        "model": model or TEXT_MODEL,
        "input": [{
            "role": "user",
            "content": content
        }]
    }
    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json=payload, timeout=180
    )
    if not r.ok:
        raise RuntimeError(f"OpenAI API error {r.status_code}: {r.text[:800]}")
    return response_text(r.json())

def transcribe(path):
    if not OPENAI_API_KEY:
        raise RuntimeError("Chưa cấu hình OPENAI_API_KEY.")
    with open(path, "rb") as f:
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            data={"model": TRANSCRIBE_MODEL},
            files={"file": (Path(path).name, f)},
            timeout=300
        )
    if not r.ok:
        raise RuntimeError(f"Transcription error {r.status_code}: {r.text[:800]}")
    return r.json().get("text", "")

def to_data_url(path):
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    raw = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{raw}"

def analyze_image(path):
    prompt = """Đọc toàn bộ chữ có trong ảnh và hiểu cả nội dung thị giác.
Trả về theo đúng cấu trúc:
TEXT_TRONG_ANH:
<text đọc được>

MO_TA_HINH_ANH:
<mô tả ngắn những gì hình ảnh thể hiện>

NGU_CANH:
<nếu có thể suy ra, nêu ngữ cảnh; nếu không thì ghi không rõ>
Không bịa nội dung không nhìn thấy."""
    return openai_response([
        {"type": "input_text", "text": prompt},
        {"type": "input_image", "image_url": to_data_url(path)}
    ], VISION_MODEL)

def extract_video(video_path):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Máy chủ chưa cài ffmpeg. Hãy cài ffmpeg để xử lý video.")
    tmp = Path(tempfile.mkdtemp(prefix="content_insight_"))
    audio = tmp / "audio.mp3"
    frames = tmp / "frame_%02d.jpg"

    subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path), "-vn",
        "-ac", "1", "-ar", "16000", "-b:a", "64k", str(audio)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 1 frame every ~8 seconds, max 12 frames after extraction
    subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", "fps=1/8,scale='min(960,iw)':-2",
        "-q:v", "4", str(frames)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_files = sorted(tmp.glob("frame_*.jpg"))[:12]
    transcript = transcribe(audio) if audio.exists() and audio.stat().st_size > 1000 else ""

    visual_notes = ""
    if frame_files:
        content = [{"type":"input_text","text":"""Đây là các frame được lấy theo thời gian từ một video.
Hãy đọc text/on-screen caption nếu có, nhận diện diễn biến chính, bối cảnh, sản phẩm/chủ thể và thông điệp thị giác.
Không cần mô tả từng frame; hãy tổng hợp thành ghi chú phục vụ việc tìm insight content."""}]
        for f in frame_files:
            content.append({"type":"input_image","image_url":to_data_url(f)})
        visual_notes = openai_response(content, VISION_MODEL)

    return transcript, visual_notes, tmp

def parse_json_loose(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise

def derive_insight(source_text, context=""):
    prompt = f"""Bạn là Senior Content Strategist cho team social/content.
Từ source bên dưới, hãy rút ra INSIGHT có thể dùng để phát triển content, không chỉ tóm tắt.

SOURCE:
{source_text}

CONTEXT / VISUAL NOTES:
{context}

Trả về CHỈ JSON hợp lệ, tiếng Việt:
{{
  "summary": "Tóm tắt source trong 1-3 câu",
  "core_insight": "Một insight cốt lõi, viết theo dạng sự thật ngầm hiểu/tâm lý/hành vi có giá trị khai thác",
  "audience": "Nhóm người insight này liên quan",
  "tension": "Mâu thuẫn, pain point, desire hoặc trigger phía sau insight",
  "content_angles": ["3-5 góc triển khai content cụ thể"],
  "hooks": ["3-5 hook/câu mở đầu có thể dùng"],
  "tags": ["3-8 tag ngắn"]
}}

Nguyên tắc:
- Phân biệt fact/observation với insight.
- Không bịa số liệu.
- Nếu source yếu hoặc thiếu ngữ cảnh, nói rõ mức độ chắc chắn trong core_insight.
- Ưu tiên insight có thể biến thành video/post/campaign."""
    raw = openai_response([{"type":"input_text","text":prompt}], TEXT_MODEL)
    return parse_json_loose(raw)

def save_insight(source_type, source_name, raw_text, insight):
    conn = db()
    cur = conn.execute("""
    INSERT INTO insights
    (created_at, source_type, source_name, raw_text, summary, core_insight, audience, tension,
     content_angles, hooks, tags, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'New')
    """, (
        datetime.now().isoformat(timespec="seconds"),
        source_type, source_name, raw_text,
        insight.get("summary",""),
        insight.get("core_insight",""),
        insight.get("audience",""),
        insight.get("tension",""),
        json.dumps(insight.get("content_angles",[]), ensure_ascii=False),
        json.dumps(insight.get("hooks",[]), ensure_ascii=False),
        json.dumps(insight.get("tags",[]), ensure_ascii=False),
    ))
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/insights")
def list_insights():
    q = request.args.get("q","").strip()
    conn = db()
    if q:
        rows = conn.execute("""
        SELECT * FROM insights
        WHERE core_insight LIKE ? OR summary LIKE ? OR tags LIKE ? OR source_name LIKE ?
        ORDER BY id DESC
        """, tuple([f"%{q}%"]*4)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM insights ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify([dict(x) for x in rows])

@app.post("/api/analyze-text")
def analyze_text_route():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    name = (data.get("name") or "Text note").strip()
    if not text:
        return jsonify({"error":"Bạn chưa nhập nội dung."}), 400
    try:
        insight = derive_insight(text)
        item_id = save_insight("text", name, text, insight)
        return jsonify({"id":item_id, "insight":insight})
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.post("/api/analyze-file")
def analyze_file_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error":"Chưa có file."}), 400

    safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", f.filename)
    target = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_name}"
    f.save(target)
    mime = f.mimetype or mimetypes.guess_type(str(target))[0] or ""

    tmp = None
    try:
        if mime.startswith("image/"):
            extracted = analyze_image(target)
            insight = derive_insight(extracted)
            item_id = save_insight("image", f.filename, extracted, insight)
            return jsonify({"id":item_id, "extracted":extracted, "insight":insight})

        if mime.startswith("video/") or target.suffix.lower() in [".mp4",".mov",".m4v",".webm",".avi",".mkv"]:
            transcript, visual_notes, tmp = extract_video(target)
            combined = f"TRANSCRIPT:\n{transcript}\n\nVISUAL NOTES:\n{visual_notes}"
            insight = derive_insight(transcript or visual_notes, visual_notes)
            item_id = save_insight("video", f.filename, combined, insight)
            return jsonify({
                "id":item_id,
                "transcript": transcript,
                "visual_notes": visual_notes,
                "insight": insight
            })

        return jsonify({"error":"Hiện MVP hỗ trợ ảnh và video. Với nội dung text, dùng tab Text."}), 400
    except Exception as e:
        return jsonify({"error":str(e)}), 500
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

@app.post("/api/insights/<int:item_id>/status")
def set_status(item_id):
    status = (request.get_json(force=True).get("status") or "New")[:30]
    conn = db()
    conn.execute("UPDATE insights SET status=? WHERE id=?", (status,item_id))
    conn.commit()
    conn.close()
    return jsonify({"ok":True})

@app.delete("/api/insights/<int:item_id>")
def delete_insight(item_id):
    conn = db()
    conn.execute("DELETE FROM insights WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok":True})

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5000")), debug=True)
