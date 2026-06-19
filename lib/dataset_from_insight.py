"""Compatibility exports for the insight hydration API.

New code should import from ``lib.insights``.
"""

from lib.insights.hydration import (
    DatasetFromInsightResult,
    InsightHydrationResult,
    dataset_from_insight,
    hydrate_dataset_from_insights,
)

__all__ = [
    "DatasetFromInsightResult",
    "InsightHydrationResult",
    "dataset_from_insight",
    "hydrate_dataset_from_insights",
]
