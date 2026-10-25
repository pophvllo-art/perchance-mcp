"""Persist generated images so the MCP tool can inline them and the REST API
can hand out a URL."""

import hashlib
import os
import time
from typing import Optional

from . import config


def image_dir() -> str:
    os.makedirs(config.IMAGE_DIR, exist_ok=True)
    return config.IMAGE_DIR


def cleanup(max_age: Optional[int] = None) -> None:
    max_age = config.IMAGE_TTL if max_age is None else max_age
    try:
        now = time.time()
        for name in os.listdir(config.IMAGE_DIR):
            path = os.path.join(config.IMAGE_DIR, name)
            if os.path.isfile(path) and now - os.path.getmtime(path) > max_age:
                os.remove(path)
    except Exception:
        pass


def save(raw: bytes, ext: str = "png") -> str:
    """Write bytes and return the file name."""
    cleanup()
    sha = hashlib.sha256(raw).hexdigest()
    name = f"{sha}.{ext}"
    path = os.path.join(image_dir(), name)
    try:
        with open(path, "wb") as fh:
            fh.write(raw)
    except Exception:
        pass
    return name


def path_for(name: str) -> str:
    return os.path.join(config.IMAGE_DIR, os.path.basename(name))


def exists(name: str) -> bool:
    try:
        return os.path.isfile(path_for(name))
    except Exception:
        return False
