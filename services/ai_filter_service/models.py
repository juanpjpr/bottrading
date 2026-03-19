from __future__ import annotations

from pydantic import BaseModel, Field


class ArticleInput(BaseModel):
    title: str = ""
    description: str = ""
    source: str = "unknown"
    published_at: str = ""
    url: str = ""


class FilterNewsRequest(BaseModel):
    articles: list[ArticleInput] = Field(default_factory=list)
