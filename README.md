
# Content Insight Hub — MVP

App nội bộ cho team Content:
- Paste text -> AI rút insight
- Upload ảnh -> đọc text trong ảnh + hiểu visual -> rút insight
- Upload video -> tách audio để transcript + lấy frame hình ảnh -> rút insight
- Lưu Insight Library bằng SQLite
- Search, status New / Approved / Used / Archived

## 1. Cài đặt

Yêu cầu: Python 3.10+ và ffmpeg (nếu phân tích video).

```bash
cd content_insight_app
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

Cài ffmpeg:
- macOS: `brew install ffmpeg`
- Ubuntu: `sudo apt install ffmpeg`
- Windows: cài ffmpeg và thêm vào PATH.

## 2. API key

macOS/Linux:
```bash
export OPENAI_API_KEY="..."
```

Windows PowerShell:
```powershell
$env:OPENAI_API_KEY="..."
```

Có thể đổi model bằng env:
```bash
export OPENAI_TEXT_MODEL="gpt-5-mini"
export OPENAI_VISION_MODEL="gpt-5-mini"
export OPENAI_TRANSCRIBE_MODEL="gpt-4o-mini-transcribe"
```

## 3. Chạy app

```bash
python app.py
```

Mở: http://localhost:5000

## Đưa cho team dùng chung

MVP có thể deploy lên Render/Railway/Fly.io/VPS. Khi deploy:
- Dùng persistent disk cho `insights.db`
- Giới hạn quyền truy cập nội bộ
- Không đưa OPENAI_API_KEY vào frontend
- Với lượng video lớn: chuyển upload sang object storage (S3/R2) và xử lý qua job queue
- Với nhiều user: thêm login + bảng users/workspaces

## Nâng cấp nên làm tiếp

1. User login + tên người submit insight
2. Folder/brand/campaign
3. Link TikTok/Instagram/YouTube -> ingest tự động (tuỳ API/quyền truy cập)
4. Duplicate detection / semantic search
5. Insight score: Novelty / Relevance / Actionability
6. Từ insight -> Brief -> Hook -> Script -> Content Calendar
7. Slack/Telegram notification khi có insight Approved
