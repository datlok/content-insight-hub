
import os, json, base64, tempfile, subprocess, shutil, re, mimetypes
from pathlib import Path
from datetime import datetime, timezone

import requests
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from PIL import Image

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


class ContentDraft(db.Model):
    __tablename__ = "content_drafts"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    insight_id = db.Column(db.Integer, db.ForeignKey("insights.id"), nullable=True)
    version_type = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(255))
    content = db.Column(db.Text, nullable=False)
    platform = db.Column(db.String(50))
    objective = db.Column(db.String(50))
    extra_request = db.Column(db.Text)
    status = db.Column(db.String(30), default="Draft")
    image_data = db.Column(db.LargeBinary, nullable=True)
    image_mime = db.Column(db.String(50), nullable=True)
    image_width = db.Column(db.Integer, nullable=True)
    image_height = db.Column(db.Integer, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "insight_id": self.insight_id,
            "version_type": self.version_type,
            "title": self.title or "",
            "content": self.content or "",
            "platform": self.platform or "",
            "objective": self.objective or "",
            "extra_request": self.extra_request or "",
            "status": self.status or "Draft",
            "has_image": bool(self.image_data),
            "image_width": self.image_width,
            "image_height": self.image_height,
        }

class DesignAsset(db.Model):
    __tablename__ = "design_assets"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    instruction = db.Column(db.Text)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    photo_count = db.Column(db.Integer, default=1)
    image_data = db.Column(db.LargeBinary, nullable=False)
    image_mime = db.Column(db.String(50), default="image/png")

    def to_dict(self):
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "instruction": self.instruction or "",
            "width": self.width,
            "height": self.height,
            "photo_count": self.photo_count or 0,
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
    prompt = f"""Bạn là Content Lead của một studio chụp ảnh cá nhân tại Việt Nam.
Nhiệm vụ là biến INSIGHT thành content có thể đăng thật, không phải bài mẫu chung chung.

CONTEXT / INSIGHT:
{insight_text}

NỀN TẢNG: {platform}
MỤC TIÊU: {objective}
YÊU CẦU THÊM CỦA TEAM:
{extra_request or "Không có"}

PHONG CÁCH BẮT BUỘC:
- Tiếng Việt tự nhiên, hiện đại, có cảm giác người thật viết.
- Không dùng văn phong sáo rỗng kiểu: "không chỉ... mà còn...", "hành trình", "chạm đến", "nâng tầm", "tỏa sáng", "phiên bản tốt nhất của bạn" nếu không thật sự cần.
- Không giảng giải insight. Hãy biến insight thành một góc nói khiến khách thấy "đúng là mình".
- Không mở bài bằng định nghĩa, câu hỏi quá chung chung hoặc lời quảng cáo.
- Ưu tiên câu ngắn, nhịp đọc tốt, có khoảng nghỉ.
- Có thể dùng ngôn ngữ đời thường nhưng không suồng sã quá mức.
- Không tự bịa giá, khuyến mãi, số liệu, tên concept hoặc quyền lợi không có trong input.
- Không hashtag trừ khi team yêu cầu.
- Không emoji trừ khi thật sự hợp ngữ cảnh.
- Không viết kiểu AI, không lặp lại cùng một ý bằng nhiều câu.
- Nếu insight nói về nỗi lo/ngại của khách, đừng phủ nhận cảm xúc; hãy cho thấy studio hiểu vấn đề rồi chuyển sang cách giải quyết cụ thể.
- CTA ngắn, tự nhiên, không ép mua.

CHỈ TẠO ĐÚNG 2 PHIÊN BẢN:

VERSION 1 — ORGANIC / HOOK MẠNH
- Dùng cho post social organic.
- Mở bằng 1 hook cụ thể, có tension hoặc observation.
- 80–160 từ.
- Mục tiêu: khiến đúng nhóm khách dừng lại và thấy mình trong đó.
- Có thể kết nhẹ bằng một câu gợi mở, không cần bán hàng mạnh.

VERSION 2 — CONVERSION / CTA
- Cùng insight nhưng triển khai theo hướng thuyết phục đặt lịch/inbox.
- 120–220 từ.
- Vẫn phải tự nhiên; bán hàng bằng việc giải tỏa rào cản và cho thấy trải nghiệm khách nhận được.
- CTA cuối bài chỉ 1–2 câu.

Trả về CHỈ JSON hợp lệ:
{{
  "short_hook": {{
    "title": "Phiên bản 1 — Organic / Hook mạnh",
    "content": "Nội dung hoàn chỉnh"
  }},
  "sales_cta": {{
    "title": "Phiên bản 2 — Conversion / CTA",
    "content": "Nội dung hoàn chỉnh"
  }}
}}

Trước khi trả kết quả, tự kiểm tra:
1. Hai phiên bản có khác nhau rõ rệt không?
2. Có câu nào nghe như AI hoặc quảng cáo sáo rỗng không? Nếu có, viết lại.
3. Hook có xuất phát trực tiếp từ tension/behavior trong insight không?
4. Có bịa thông tin không? Nếu có, xóa."""
    raw = openai_response([{"type":"input_text","text":prompt}], TEXT_MODEL)
    return parse_json_loose(raw)

def choose_generation_size(width, height):
    ratio = width / max(height, 1)
    if ratio >= 1.25:
        return "1536x1024"
    if ratio <= 0.8:
        return "1024x1536"
    return "1024x1024"

def crop_resize_to_target(image_bytes, width, height):
    src_fd, src_name = tempfile.mkstemp(suffix=".png")
    out_fd, out_name = tempfile.mkstemp(suffix=".png")
    os.close(src_fd)
    os.close(out_fd)
    src_path = Path(src_name)
    out_path = Path(out_name)
    try:
        src_path.write_bytes(image_bytes)
        with Image.open(src_path) as im:
            im = im.convert("RGB")
            target_ratio = width / max(height, 1)
            src_ratio = im.width / max(im.height, 1)
            if src_ratio > target_ratio:
                new_w = int(im.height * target_ratio)
                left = max((im.width - new_w) // 2, 0)
                im = im.crop((left, 0, left + new_w, im.height))
            elif src_ratio < target_ratio:
                new_h = int(im.width / target_ratio)
                top = max((im.height - new_h) // 2, 0)
                im = im.crop((0, top, im.width, top + new_h))
            im = im.resize((width, height), Image.Resampling.LANCZOS)
            im.save(out_path, format="PNG", optimize=True)
        return out_path.read_bytes()
    finally:
        src_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)

def generate_design_from_refs(ref_path, photo_paths, instruction, width=1600, height=800):
    if not OPENAI_API_KEY:
        raise RuntimeError("Chưa cấu hình OPENAI_API_KEY trên Render.")
    photo_paths = list(photo_paths or [])
    if not photo_paths:
        raise RuntimeError("Chưa có ảnh chụp của team.")

    prompt = f"""Tạo một social design MỚI dựa trên các ảnh input.

Ảnh đầu tiên = REFERENCE DESIGN:
- Học bố cục, hierarchy, spacing, typography treatment, màu sắc và mood.
- Không sao chép logo, watermark, tên thương hiệu hoặc text từ reference.

Các ảnh còn lại = ẢNH CHỤP CỦA TEAM:
- Đây là nguồn hình ảnh chính.
- Có thể chọn một hoặc phối hợp nhiều ảnh nếu phù hợp layout.
- Ưu tiên giữ nhận diện khuôn mặt, trang phục, sản phẩm và chi tiết quan trọng.
- Không tự thay người hoặc làm biến dạng chủ thể nếu không được yêu cầu.

YÊU CẦU:
{instruction}

OUTPUT MONG MUỐN:
- Kích thước cuối: {width}x{height}px.
- Tỷ lệ: {width}:{height}.
- Bố cục phải được thiết kế ngay từ đầu để phù hợp tỷ lệ này.
- Giữ text/chủ thể quan trọng trong vùng an toàn để crop cuối không cắt mất.

Nếu có text tiếng Việt, ưu tiên rõ, đúng chính tả và hierarchy tốt."""

    gen_size = choose_generation_size(width, height)
    handles, files = [], []
    try:
        for p in [ref_path] + photo_paths:
            h = open(p, "rb")
            handles.append(h)
            files.append(("image[]", (Path(p).name, h, mimetypes.guess_type(str(p))[0] or "image/png")))

        r = requests.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            data={"model": IMAGE_MODEL, "prompt": prompt, "size": gen_size, "quality": "medium"},
            files=files,
            timeout=420,
        )
        if not r.ok:
            raise RuntimeError(f"Image API error {r.status_code}: {r.text[:1200]}")
        b64 = r.json().get("data", [{}])[0].get("b64_json")
        if not b64:
            raise RuntimeError("Image API không trả về ảnh.")

        final_bytes = crop_resize_to_target(base64.b64decode(b64), width, height)
        return base64.b64encode(final_bytes).decode("ascii")
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
    platform = (data.get("platform") or "Facebook").strip()
    objective = (data.get("objective") or "Bán hàng").strip()
    extra_request = (data.get("extra_request") or "").strip()

    if not insight:
        return jsonify({"error": "Chưa có insight để viết content."}), 400

    try:
        result = write_content_versions(insight, platform, objective, extra_request)
        for key, version_type in [("short_hook", "organic"), ("sales_cta", "conversion")]:
            item = result.get(key) or {}
            draft = ContentDraft(
                version_type=version_type,
                title=item.get("title", ""),
                content=item.get("content", ""),
                platform=platform,
                objective=objective,
                extra_request=extra_request,
                status="Draft",
            )
            db.session.add(draft)
            db.session.flush()
            item["draft_id"] = draft.id

        db.session.commit()
        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.post("/api/generate-design")
def generate_design_route():
    ref = request.files.get("reference")
    photos = [f for f in request.files.getlist("photos") if f and f.filename]
    instruction = (request.form.get("instruction") or "").strip()
    draft_id_raw = (request.form.get("draft_id") or "").strip()

    try:
        width = int(request.form.get("width") or 1600)
        height = int(request.form.get("height") or 800)
    except ValueError:
        return jsonify({"error": "Width và Height phải là số nguyên."}), 400

    if not ref or not ref.filename:
        return jsonify({"error": "Hãy upload ảnh reference design."}), 400
    if not photos:
        return jsonify({"error": "Hãy upload ít nhất 1 ảnh chụp bên mình."}), 400
    if len(photos) > 10:
        return jsonify({"error": "Tối đa 10 ảnh chụp cho một lần tạo design."}), 400
    if not instruction:
        return jsonify({"error": "Hãy nhập yêu cầu thiết kế."}), 400

    draft_id = int(draft_id_raw) if draft_id_raw.isdigit() else None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    ref_path = UPLOAD_DIR / f"ref_{stamp}_{re.sub(r'[^A-Za-z0-9._ -]+', '_', ref.filename)}"
    ref.save(ref_path)
    photo_paths = []

    try:
        for idx, photo in enumerate(photos, start=1):
            name = re.sub(r'[^A-Za-z0-9._ -]+', '_', photo.filename)
            p = UPLOAD_DIR / f"photo_{stamp}_{idx}_{name}"
            photo.save(p)
            photo_paths.append(p)

        b64 = generate_design_from_refs(ref_path, photo_paths, instruction, width=width, height=height)
        image_bytes = base64.b64decode(b64)

        if draft_id:
            draft = db.session.get(ContentDraft, draft_id)
            if not draft:
                return jsonify({"error": "Không tìm thấy content draft để gắn ảnh."}), 404
            draft.image_data = image_bytes
            draft.image_mime = "image/png"
            draft.image_width = width
            draft.image_height = height
            library = "content"
            saved_id = draft.id
        else:
            asset = DesignAsset(
                instruction=instruction,
                width=width,
                height=height,
                photo_count=len(photo_paths),
                image_data=image_bytes,
                image_mime="image/png",
            )
            db.session.add(asset)
            db.session.flush()
            library = "design"
            saved_id = asset.id

        db.session.commit()
        return jsonify({
            "image_base64": b64,
            "mime": "image/png",
            "width": width,
            "height": height,
            "photo_count": len(photo_paths),
            "library": library,
            "saved_id": saved_id,
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        ref_path.unlink(missing_ok=True)
        for p in photo_paths:
            p.unlink(missing_ok=True)


@app.get("/api/content-library")
def content_library():
    rows = ContentDraft.query.order_by(ContentDraft.id.desc()).limit(200).all()
    return jsonify([x.to_dict() for x in rows])

@app.get("/api/content-library/<int:item_id>/image")
def content_library_image(item_id):
    item = db.session.get(ContentDraft, item_id)
    if not item or not item.image_data:
        return jsonify({"error": "Ảnh không tồn tại."}), 404
    return app.response_class(item.image_data, mimetype=item.image_mime or "image/png")

@app.post("/api/content-library/<int:item_id>/status")
def content_library_status(item_id):
    item = db.session.get(ContentDraft, item_id)
    if not item:
        return jsonify({"error": "Content không tồn tại."}), 404
    item.status = (request.get_json(force=True).get("status") or "Draft")[:30]
    db.session.commit()
    return jsonify({"ok": True})

@app.get("/api/design-library")
def design_library():
    rows = DesignAsset.query.order_by(DesignAsset.id.desc()).limit(200).all()
    return jsonify([x.to_dict() for x in rows])

@app.get("/api/design-library/<int:item_id>/image")
def design_library_image(item_id):
    item = db.session.get(DesignAsset, item_id)
    if not item:
        return jsonify({"error": "Design không tồn tại."}), 404
    return app.response_class(item.image_data, mimetype=item.image_mime or "image/png")

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
