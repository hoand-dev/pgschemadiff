"""Connection profile domain models.

Pure domain — không phụ thuộc Textual, psycopg, hay bất kỳ infrastructure nào.
"""

from __future__ import annotations

from urllib.parse import quote

from pydantic import BaseModel, Field


class ConnectionInfo(BaseModel):
    """Thông tin kết nối tới một PostgreSQL database."""

    model_config = {"frozen": True}

    host: str
    port: int = 5432
    database: str
    user: str
    # Kept out of repr so tracebacks, logs and assertion output never show it.
    password: str = Field(default="", repr=False)

    def display(self) -> str:
        """Hiển thị dạng URL ngắn gọn, ẩn password."""
        return f"postgres://{self.user}@{self.host}:{self.port}/{self.database}"

    def dsn(self) -> str:
        """DSN đầy đủ để truyền cho psycopg."""
        user = quote(self.user, safe="")
        password = f":{quote(self.password, safe='')}" if self.password else ""
        host = self.host
        if ":" in host and not (host.startswith("[") and host.endswith("]")):
            host = f"[{host}]"
        database = quote(self.database, safe="")
        return f"postgresql://{user}{password}@{host}:{self.port}/{database}"


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
