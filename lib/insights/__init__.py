from lib.insights.context import INSUFFICIENT_CONTEXT
from lib.insights.file import InsightFile
from lib.insights.hydration import dataset_from_insight, select_insights
from lib.insights.naming import insight_model_slug, strip_model_tag

InsightResult = list[InsightFile]

__all__ = [
    "InsightFile",
    "InsightResult",
    "INSUFFICIENT_CONTEXT",
    "dataset_from_insight",
    "select_insights",
    "strip_model_tag",
    "insight_model_slug",
]
