#!/usr/bin/env python3
from datetime import datetime, timezone
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

BACKEND_ROOT = Path(__file__).resolve().parent
OBJECTS_DIR = BACKEND_ROOT / "objects"

app = FastAPI(title="Scribble To 3D Upload API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def make_file_safe_stem(label: str, fallback: str = "object") -> str:
    stem = re.sub(r"[\\/:*?\"<>|]+", " ", label or "")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or fallback


@app.post("/upload-latest-box")
async def upload_latest_box(
    image: UploadFile = File(...),
    label: str = Form(default=""),
    globalPrompt: str = Form(default=""),
    box: str = Form(default=""),
):
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Field 'image' must be an image file.")

    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")

    OBJECTS_DIR.mkdir(parents=True, exist_ok=True)

    safe_label = make_file_safe_stem(label, "latest-box")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    output_name = f"{safe_label}-{timestamp}.png"
    output_path = OBJECTS_DIR / output_name
    output_path.write_bytes(data)

    try:
        saved_to = str(output_path.relative_to(BACKEND_ROOT))
    except ValueError:
        saved_to = str(output_path)

    return {
        "status": "ok",
        "saved_to": saved_to,
        "filename": output_name,
        "label": label,
        "globalPrompt": globalPrompt,
        "box": box,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("upload_server:app", host="0.0.0.0", port=8000, reload=True)
