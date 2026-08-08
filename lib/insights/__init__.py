from lib.insights.file import InsightFile
from lib.insights.hydration import dataset_from_insight
from lib.insights.naming import insight_model_slug, strip_model_tag

InsightResult = list[InsightFile]

__all__ = [
    "InsightFile",
    "InsightResult",
    "dataset_from_insight",
    "strip_model_tag",
    "insight_model_slug",
]
