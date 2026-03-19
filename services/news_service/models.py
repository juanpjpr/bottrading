from __future__ import annotations

from pydantic import BaseModel


class NewsFetchQuery(BaseModel):
    news_file: str = "sample_news.json"
    fetch_news: bool = False
    query: str | None = None
