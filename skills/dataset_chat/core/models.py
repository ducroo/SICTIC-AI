from pydantic import BaseModel
from typing import Optional, Union
from lib.logger import get_logger

logger = get_logger(__name__)


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
