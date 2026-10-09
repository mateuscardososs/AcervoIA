from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_type: Literal["process", "embeddings"]
    status: Literal["pending", "processing", "completed", "failed"]
    progress: int
    attempt_count: int
    error: str | None
    result_count: int | None
    embedding_model: str | None
    embedding_provider: str | None
    created_at: datetime
    updated_at: datetime
