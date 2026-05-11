from pydantic import BaseModel
from typing import Optional, Union
from skills.utils.logger import get_logger

logger = get_logger(__name__)


class Chunk(BaseModel):
    chunk_id: str
    document_name: str
    page_number: Union[int, str]
    last_modified: float
    text: str
    score: Optional[float] = None
