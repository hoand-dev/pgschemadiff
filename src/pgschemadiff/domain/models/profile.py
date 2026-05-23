"""Connection profile domain models.

Pure domain — no Textual, psycopg, or infrastructure dependencies.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConnectionInfo(BaseModel):
    model_config = {"frozen": True}

    host: str
    port: int = 5432
    database: str
    user: str
    password: str = ""

    def display(self) -> str:
        return f"postgres://{self.user}@{self.host}:{self.port}/{self.database}"

    def dsn(self) -> str:
        pwd = f":{self.password}" if self.password else ""
        return f"postgresql://{self.user}{pwd}@{self.host}:{self.port}/{self.database}"


class Profile(BaseModel):
    model_config = {"frozen": True}

    name: str
    source: ConnectionInfo
    target: ConnectionInfo
    schemas: list[str] = Field(default_factory=lambda: ["public"])
    ignore_patterns: list[str] = Field(default_factory=list)
    mode: str = "schema-only"

    def summary(self) -> str:
        return f"{self.source.host} / {self.target.host}"
