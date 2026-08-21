"""Runtime configuration.

Everything is env-overridable so the same image runs on Mario's laptop (bare
uvicorn) and on the analyst's Windows box (docker-compose with volumes).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: _env_path("BUC_DATA_DIR", Path.cwd() / "data"))

    # Deliverable/export normalization. Mixed sources (different matches,
    # YouTube vs local file) only concat cleanly if every segment is encoded
    # with identical parameters.
    export_width: int = field(default_factory=lambda: _env_int("BUC_EXPORT_WIDTH", 1280))
    export_height: int = field(default_factory=lambda: _env_int("BUC_EXPORT_HEIGHT", 720))
    export_fps: int = field(default_factory=lambda: _env_int("BUC_EXPORT_FPS", 30))
    export_crf: int = field(default_factory=lambda: _env_int("BUC_EXPORT_CRF", 20))
    export_preset: str = field(default_factory=lambda: os.environ.get("BUC_EXPORT_PRESET", "veryfast"))

    # Proxy: 480p with a short GOP so browser scrubbing lands near-instantly.
    proxy_height: int = field(default_factory=lambda: _env_int("BUC_PROXY_HEIGHT", 480))
    proxy_gop: int = field(default_factory=lambda: _env_int("BUC_PROXY_GOP", 25))
    proxy_crf: int = field(default_factory=lambda: _env_int("BUC_PROXY_CRF", 28))

    # Tagging defaults (assumption #1 in the spec -- tune after first real use).
    tag_pad_before_s: float = field(default_factory=lambda: float(os.environ.get("BUC_TAG_PAD_BEFORE", 3.0)))
    tag_pad_after_s: float = field(default_factory=lambda: float(os.environ.get("BUC_TAG_PAD_AFTER", 27.0)))

    ffmpeg: str = field(default_factory=lambda: os.environ.get("BUC_FFMPEG", "ffmpeg"))
    ffprobe: str = field(default_factory=lambda: os.environ.get("BUC_FFPROBE", "ffprobe"))
    ytdlp: str = field(default_factory=lambda: os.environ.get("BUC_YTDLP", "yt-dlp"))

    # Directory holding the built Next.js export; served by FastAPI in handoff mode.
    frontend_dir: Path | None = field(
        default_factory=lambda: (Path(os.environ["BUC_FRONTEND_DIR"]).resolve() if os.environ.get("BUC_FRONTEND_DIR") else None)
    )

    @property
    def db_dir(self) -> Path:
        return self.data_dir / "db"

    @property
    def db_path(self) -> Path:
        return self.db_dir / "buc.sqlite3"

    @property
    def video_dir(self) -> Path:
        return self.data_dir / "videos"

    @property
    def source_dir(self) -> Path:
        return self.video_dir / "source"

    @property
    def proxy_dir(self) -> Path:
        return self.video_dir / "proxy"

    @property
    def clip_dir(self) -> Path:
        return self.video_dir / "clips"

    @property
    def export_dir(self) -> Path:
        return self.video_dir / "exports"

    @property
    def work_dir(self) -> Path:
        return self.video_dir / "work"

    def ensure_dirs(self) -> None:
        for d in (self.db_dir, self.source_dir, self.proxy_dir, self.clip_dir, self.export_dir, self.work_dir):
            d.mkdir(parents=True, exist_ok=True)

    def media_roots(self) -> list[Path]:
        """Directories a media file may legitimately be served from."""
        return [self.source_dir, self.proxy_dir, self.clip_dir, self.export_dir]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Test hook -- forces re-read of the environment."""
    global _settings
    _settings = None
