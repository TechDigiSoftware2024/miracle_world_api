from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.core.config import MIRACLE_WORLD_UPLOAD_ROOT

_SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]+")
_CHUNK_SIZE = 1024 * 1024


def _safe_name(name: str) -> str:
    cleaned = _SAFE_CHARS_RE.sub("_", name.strip())
    return cleaned.strip("._-") or "file"


def save_upload_file(upload: UploadFile, subdir: str) -> str:
    filename = _safe_name(upload.filename or "file")
    suffix = Path(filename).suffix
    base = Path(filename).stem
    unique_name = f"{base}_{uuid4().hex}{suffix}"

    root = Path(MIRACLE_WORLD_UPLOAD_ROOT)
    target_dir = root / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / unique_name

    try:
        with target_path.open("wb") as out:
            while True:
                chunk = upload.file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                out.write(chunk)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save upload file in {target_dir}",
        ) from exc
    finally:
        upload.file.close()

    return str(target_path).replace("\\", "/")
