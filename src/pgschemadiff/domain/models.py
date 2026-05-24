"""Connection profile domain models.

Pure domain — không phụ thuộc Textual, psycopg, hay bất kỳ infrastructure nào.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectionInfo(BaseModel):
    """Thông tin kết nối tới một PostgreSQL database."""

    model_config = {"frozen": True}

    host: str
    port: int = 5432
    database: str
    user: str
    password: str = ""

    def display(self) -> str:
        """Hiển thị dạng URL ngắn gọn, ẩn password."""
        return f"postgres://{self.user}@{self.host}:{self.port}/{self.database}"

    def dsn(self) -> str:
        """DSN đầy đủ để truyền cho psycopg."""
        pwd = f":{self.password}" if self.password else ""
        return f"postgresql://{self.user}{pwd}@{self.host}:{self.port}/{self.database}"


class Profile(BaseModel):
    """Một cặp source → target để so sánh."""

    model_config = {"frozen": True}

    name: str
    source: ConnectionInfo
    target: ConnectionInfo
    schemas: list[str] = Field(default_factory=lambda: ["public"])
    ignore_patterns: list[str] = Field(default_factory=list)
    mode: str = "schema-only"

    def summary(self) -> str:
        """Tóm tắt 1 dòng cho list view."""
        return f"{self.source.host} / {self.target.host}"
