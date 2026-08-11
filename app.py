
import os, json, base64, tempfile, subprocess, shutil, re, mimetypes
from pathlib import Path
from datetime import datetime, timezone

import requests
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy

APP_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(tempfile.gettempdir()) / "content_insight_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-5-mini")
VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", TEXT_MODEL)
TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2")

def database_uri():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{APP_DIR / 'insights.db'}"
    # Force SQLAlchemy to use psycopg v3.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = 250 * 1024 * 1024
app.config["SQLALCHEMY_DATABASE_URI"] = database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 280,
}

db = SQLAlchemy(app)

class Insight(db.Model):
    __tablename__ = "insights"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    source_type = db.Column(db.String(20), nullable=False)
    source_name = db.Column(db.String(255))
    raw_text = db.Column(db.Text)
    summary = db.Column(db.Text)
    core_insight = db.Column(db.Text)
    audience = db.Column(db.Text)
    tension = db.Column(db.Text)
    content_angles = db.Column(db.Text)
    hooks = db.Column(db.Text)
    tags = db.Column(db.Text)
    status = db.Column(db.String(30), default="New")

    def to_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "source_type": self.source_type,
            "source_name": self.source_name or "",
            "raw_text": self.raw_text or "",
            "summary": self.summary or "",
            "core_insight": self.core_insight or "",
            "audience": self.audience or "",
            "tension": self.tension or "",
            "content_angles": self.content_angles or "[]",
            "hooks": self.hooks or "[]",
            "tags": self.tags or "[]",
            "status": self.status or "New",
        }

def init_db():
    with app.app_context():
        db.create_all()

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
        raise RuntimeError("Chưa cấu hình OPENAI_API_KEY trên Render.")
    payload = {
        "model": model or TEXT_MODEL,
        "input": [{"role": "user", "content": content}],
    }
    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    if not r.ok:
        raise RuntimeError(f"OpenAI API error {r.status_code}: {r.text[:800]}")
    return response_text(r.json())

def transcribe(path):
    if not OPENAI_API_KEY:
        raise RuntimeError("Chưa cấu hình OPENAI_API_KEY trên Render.")
    with open(path, "rb") as f:
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            data={"model": TRANSCRIBE_MODEL},
            files={"file": (Path(path).name, f)},
            timeout=300,
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
        {"type": "input_image", "image_url": to_data_url(path)},
    ], VISION_MODEL)

def extract_video(video_path):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("Server chưa có ffmpeg.")
    tmp = Path(tempfile.mkdtemp(prefix="content_insight_"))
    audio = tmp / "audio.mp3"
    frames = tmp / "frame_%02d.jpg"

    subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path), "-vn",
        "-ac", "1", "-ar", "16000", "-b:a", "48k", str(audio),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", "fps=1/8,scale='min(960,iw)':-2",
        "-frames:v", "12", "-q:v", "4", str(frames),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_files = sorted(tmp.glob("frame_*.jpg"))[:12]
    transcript = transcribe(audio) if audio.exists() and audio.stat().st_size > 1000 else ""

    visual_notes = ""
    if frame_files:
        content = [{
            "type": "input_text",
            "text": """Đây là các frame được lấy theo thời gian từ một video.
Hãy đọc text/on-screen caption nếu có, nhận diện diễn biến chính, bối cảnh, sản phẩm/chủ thể và thông điệp thị giác.
Không cần mô tả từng frame; hãy tổng hợp thành ghi chú phục vụ việc tìm insight content."""
        }]
        for f in frame_files:
            content.append({"type": "input_image", "image_url": to_data_url(f)})
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
        raise ValueError("AI trả về dữ liệu không đúng định dạng JSON.")

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
    raw = openai_response([{"type": "input_text", "text": prompt}], TEXT_MODEL)
    return parse_json_loose(raw)

def save_insight(source_type, source_name, raw_text, insight):
    item = Insight(
        source_type=source_type,
        source_name=source_name,
        raw_text=raw_text,
        summary=insight.get("summary", ""),
        core_insight=insight.get("core_insight", ""),
        audience=insight.get("audience", ""),
        tension=insight.get("tension", ""),
        content_angles=json.dumps(insight.get("content_angles", []), ensure_ascii=False),
        hooks=json.dumps(insight.get("hooks", []), ensure_ascii=False),
        tags=json.dumps(insight.get("tags", []), ensure_ascii=False),
        status="New",
    )
    db.session.add(item)
    db.session.commit()
    return item.id


def write_content_versions(insight_text, platform="Facebook", objective="Bán hàng", extra_request=""):
    prompt = f"""Bạn là Senior Social Content Writer.
Dựa trên insight dưới đây, viết ĐÚNG 2 phiên bản content. Không tạo storytelling riêng.

INSIGHT:
{insight_text}

NỀN TẢNG: {platform}
MỤC TIÊU: {objective}
YÊU CẦU THÊM: {extra_request or "Không có"}

Trả về CHỈ JSON hợp lệ:
{{
  "short_hook": {{"title":"Phiên bản 1 — Hook mạnh","content":"Nội dung hoàn chỉnh"}},
  "sales_cta": {{"title":"Phiên bản 2 — Bán hàng / CTA","content":"Nội dung hoàn chỉnh"}}
}}
Phiên bản 1: ngắn, hook mạnh, dễ đọc, giữ attention.
Phiên bản 2: thuyết phục hơn, hướng tới chuyển đổi nhưng không quảng cáo lộ liễu.
Không bịa giá, ưu đãi hoặc số liệu."""
    raw = openai_response([{"type":"input_text","text":prompt}], TEXT_MODEL)
    return parse_json_loose(raw)

def generate_design_from_refs(ref_path, photo_path, instruction, size="1024x1024"):
    if not OPENAI_API_KEY:
        raise RuntimeError("Chưa cấu hình OPENAI_API_KEY trên Render.")
    prompt = f"""Tạo một social design MỚI dựa trên hai ảnh input.

Ảnh 1 = REFERENCE DESIGN:
- Học bố cục, hierarchy, spacing, typography treatment, màu sắc và mood.
- Không sao chép logo, watermark, tên thương hiệu hoặc nội dung chữ từ reference.

Ảnh 2 = ẢNH CHỤP CỦA TEAM:
- Đây là chủ thể/nội dung chính phải dùng trong thiết kế mới.
- Giữ nhận diện và chi tiết quan trọng của ảnh này tốt nhất có thể.

YÊU CẦU:
{instruction}

Tạo thiết kế mới có tinh thần/layout tham khảo từ ảnh 1 nhưng dùng ảnh 2 làm nội dung chính.
Nếu có text tiếng Việt, ưu tiên rõ, đúng chính tả và hierarchy tốt."""
    handles, files = [], []
    try:
        for p in [ref_path, photo_path]:
            h = open(p, "rb")
            handles.append(h)
            files.append(("image[]", (Path(p).name, h, mimetypes.guess_type(str(p))[0] or "image/png")))
        r = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            data={"model": IMAGE_MODEL, "prompt": prompt, "size": size, "quality": "medium"},
            files=files,
            timeout=420,
        )
        if not r.ok:
            raise RuntimeError(f"Image API error {r.status_code}: {r.text[:1200]}")
        b64 = r.json().get("data", [{}])[0].get("b64_json")
        if not b64:
            raise RuntimeError("Image API không trả về ảnh.")
        return b64
    finally:
        for h in handles:
            try:
                h.close()
            except Exception:
                pass

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"ok": True, "database": "connected"}), 200
    except Exception as e:
        return jsonify({"ok": False, "database": str(e)}), 503

@app.get("/api/insights")
def list_insights():
    q = request.args.get("q", "").strip()
    query = Insight.query
    if q:
        pattern = f"%{q}%"
        query = query.filter(db.or_(
            Insight.core_insight.ilike(pattern),
            Insight.summary.ilike(pattern),
            Insight.tags.ilike(pattern),
            Insight.source_name.ilike(pattern),
        ))
    rows = query.order_by(Insight.id.desc()).limit(200).all()
    return jsonify([x.to_dict() for x in rows])

@app.post("/api/analyze-text")
def analyze_text_route():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    name = (data.get("name") or "Text note").strip()
    if not text:
        return jsonify({"error": "Bạn chưa nhập nội dung."}), 400
    try:
        insight = derive_insight(text)
        item_id = save_insight("text", name, text, insight)
        return jsonify({"id": item_id, "insight": insight})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.post("/api/analyze-file")
def analyze_file_route():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Chưa có file."}), 400

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
            return jsonify({"id": item_id, "extracted": extracted, "insight": insight})

        if mime.startswith("video/") or target.suffix.lower() in [".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"]:
            transcript, visual_notes, tmp = extract_video(target)
            combined = f"TRANSCRIPT:\n{transcript}\n\nVISUAL NOTES:\n{visual_notes}"
            insight = derive_insight(transcript or visual_notes, visual_notes)
            item_id = save_insight("video", f.filename, combined, insight)
            return jsonify({
                "id": item_id,
                "transcript": transcript,
                "visual_notes": visual_notes,
                "insight": insight,
            })

        return jsonify({"error": "Hiện MVP hỗ trợ ảnh và video. Với nội dung text, dùng tab Text."}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


@app.post("/api/write-content")
def write_content_route():
    data = request.get_json(force=True)
    insight = (data.get("insight") or "").strip()
    if not insight:
        return jsonify({"error": "Chưa có insight để viết content."}), 400
    try:
        result = write_content_versions(
            insight,
            (data.get("platform") or "Facebook").strip(),
            (data.get("objective") or "Bán hàng").strip(),
            (data.get("extra_request") or "").strip(),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/generate-design")
def generate_design_route():
    ref = request.files.get("reference")
    photo = request.files.get("photo")
    instruction = (request.form.get("instruction") or "").strip()
    size = (request.form.get("size") or "1024x1024").strip()

    if not ref or not ref.filename:
        return jsonify({"error": "Hãy upload ảnh reference design."}), 400
    if not photo or not photo.filename:
        return jsonify({"error": "Hãy upload ảnh chụp bên mình."}), 400
    if not instruction:
        return jsonify({"error": "Hãy nhập yêu cầu thiết kế."}), 400
    if size not in ["1024x1024", "1536x1024", "1024x1536"]:
        size = "1024x1024"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ref_path = UPLOAD_DIR / f"ref_{stamp}_{re.sub(r'[^A-Za-z0-9._ -]+', '_', ref.filename)}"
    photo_path = UPLOAD_DIR / f"photo_{stamp}_{re.sub(r'[^A-Za-z0-9._ -]+', '_', photo.filename)}"
    ref.save(ref_path)
    photo.save(photo_path)

    try:
        b64 = generate_design_from_refs(ref_path, photo_path, instruction, size)
        return jsonify({"image_base64": b64, "mime": "image/png"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        ref_path.unlink(missing_ok=True)
        photo_path.unlink(missing_ok=True)

@app.post("/api/insights/<int:item_id>/status")
def set_status(item_id):
    item = db.session.get(Insight, item_id)
    if not item:
        return jsonify({"error": "Insight không tồn tại."}), 404
    item.status = (request.get_json(force=True).get("status") or "New")[:30]
    db.session.commit()
    return jsonify({"ok": True})

@app.delete("/api/insights/<int:item_id>")
def delete_insight(item_id):
    item = db.session.get(Insight, item_id)
    if not item:
        return jsonify({"error": "Insight không tồn tại."}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"ok": True})

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
