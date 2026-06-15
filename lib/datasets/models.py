from dataclasses import dataclass, field
from typing import Optional, Union

from pydantic import BaseModel

from lib.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class IngestionFailure:
    filename: str
    stage: str
    error: str


@dataclass
class IngestionResult:
    dataset: str
    converted: int = 0
    ignored: int = 0
    indexed: int = 0
    removed_parsed: int = 0
    removed_qdrant: int = 0
    failures: list[IngestionFailure] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


class Chunk(BaseModel):
    chunk_id: str
    document_name: str
    page_number: Union[int, str]
    last_modified: float
    text: str
    score: Optional[float] = None

    def to_md(self) -> str:
        """Renders the chunk as a standalone Markdown block."""
        return f"### Source: {self.document_name} | Page: {self.page_number}\n\n{self.text.strip()}"
