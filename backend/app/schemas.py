"""Request/response models."""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

SourceType = Literal["file", "youtube"]


class MatchCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    opponent: str = ""
    date: str | None = None
    source_type: SourceType
    source_url: str | None = None
    file_path: str | None = None

    @model_validator(mode="after")
    def _check_source(self) -> "MatchCreate":
        if self.source_type == "youtube":
            url = (self.source_url or "").strip()
            if not url:
                raise ValueError("source_url is required for a youtube source")
            if urlparse(url).scheme not in ("http", "https"):
                raise ValueError("source_url must be an http(s) URL")
            self.source_url = url
        if self.source_type == "file" and not (self.file_path or "").strip():
            raise ValueError("file_path is required for a file source")
        return self


class TagCreate(BaseModel):
    """Either a single hotkey moment (``t``) or an explicit window."""
    t: float | None = None
    t_start: float | None = None
    t_end: float | None = None
    note: str | None = None
    category: str = "gk_buildup"
    source: str = "manual"

    @model_validator(mode="after")
    def _check_window(self) -> "TagCreate":
        if self.t is None and (self.t_start is None or self.t_end is None):
            raise ValueError("provide either t, or both t_start and t_end")
        if (self.t_start is None) != (self.t_end is None):
            raise ValueError("t_start and t_end must be given together")
        if self.t_start is not None and self.t_end is not None and self.t_end <= self.t_start:
            raise ValueError("t_end must be greater than t_start")
        return self


class TagUpdate(BaseModel):
    t_start: float | None = None
    t_end: float | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check_window(self) -> "TagUpdate":
        if self.t_start is not None and self.t_end is not None and self.t_end <= self.t_start:
            raise ValueError("t_end must be greater than t_start")
        return self


class ClipUpdate(BaseModel):
    status: Literal["pending", "approved", "rejected"] | None = None
    note: str | None = None


class ClipReorder(BaseModel):
    clip_ids: list[int] = Field(min_length=1)


class ExportCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    clip_ids: list[int] | None = None
    match_id: int | None = None
