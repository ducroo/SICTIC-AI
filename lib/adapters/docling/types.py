from dataclasses import dataclass
from enum import Enum


class ConversionStatus(str, Enum):
    SUCCESS = "success"
    IGNORED_EMPTY = "ignored_empty"
    FAILED = "failed"


@dataclass(frozen=True)
class DocumentConversionResult:
    filename: str
    status: ConversionStatus
    text: str = ""
    error: str = ""
    reason: str = ""
