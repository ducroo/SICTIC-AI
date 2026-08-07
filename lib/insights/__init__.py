from lib.insights.discovery import StoredInsight, discover_insights
from lib.insights.file import InsightFile
from lib.insights.hydration import (
    DatasetFromInsightResult,
    InsightHydrationResult,
    dataset_from_insight,
    hydrate_dataset_from_insights,
)
from lib.insights.naming import insight_model_slug, strip_model_tag

InsightResult = list[InsightFile]

__all__ = [
    "DatasetFromInsightResult",
    "InsightFile",
    "InsightHydrationResult",
    "InsightResult",
    "StoredInsight",
    "dataset_from_insight",
    "discover_insights",
    "hydrate_dataset_from_insights",
    "strip_model_tag",
    "insight_model_slug",
]
