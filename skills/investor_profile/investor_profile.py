from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import List

from lib.insights import InsightFile, InsightResult, insight_base_name
from lib.logger import get_logger
from lib.people.model import Person
from lib.slugify import slugify
from lib.storage import get_storage
from lib.datasets.paths import dataset_insights_path, dataset_raw_path

logger = get_logger(__name__)


@dataclass(frozen=True)
class InvestorProfileResult:
    source_dataset: str
    person_profiles: int = 0
    written: int = 0
    unchanged: int = 0
    skipped: int = 0
    missing_track_records: int = 0
    insights: InsightResult = field(default_factory=list)


def _compose_investor_profile(person_profile: str, track_record: str | None) -> str:
    track_record_content = (
        track_record.strip()
        if track_record and track_record.strip()
        else "No investment track record available, likely has not invested before."
    )
    return (
        person_profile.rstrip()
        + "\n\n## Investment Track Record and Preferences\n\n"
        + track_record_content
        + "\n"
    )


async def _investor_profile_result(
    source_dataset: str = "sictic-members",
) -> InvestorProfileResult:
    """Build investor profiles by appending manual track records to person profiles."""
    dataset_slug = slugify(source_dataset)
    storage = get_storage()
    person_profile_dir = f"{dataset_insights_path(dataset_slug)}/person-profile"
    investor_profile_dir = f"{dataset_insights_path(dataset_slug)}/investor-profile"
    track_record_dir = f"{dataset_raw_path(dataset_slug)}/track-record"

    if not storage.exists(person_profile_dir):
        logger.warning(f"[{dataset_slug}] Person profile directory not found: {person_profile_dir}")
        return InvestorProfileResult(source_dataset=dataset_slug)

    filenames = storage.list(person_profile_dir, suffix=".md")
    written = 0
    unchanged = 0
    skipped = 0
    missing_track_records = 0
    insights: InsightResult = []

    for filename in filenames:
        stem = PurePosixPath(filename).stem
        linkedin_id = insight_base_name(filename)
        if not linkedin_id or linkedin_id == stem:
            logger.warning(f"[{dataset_slug}] Skipping malformed person profile filename: {filename}")
            skipped += 1
            continue

        source_path = f"{person_profile_dir}/{filename}"
        track_record_path = f"{track_record_dir}/{linkedin_id}.md"
        source_model = stem[len(linkedin_id) + 1 :]
        insight = InsightFile(
            dataset=dataset_slug,
            skill="investor_profile",
            model=source_model,
            identifier=linkedin_id,
            subdir=True,
            prompt_key="compose person profile with investment track record",
        )

        try:
            person_profile_content = storage.read_text(source_path)
            track_record_content = (
                storage.read_text(track_record_path)
                if storage.exists(track_record_path)
                else None
            )
            if track_record_content is None:
                missing_track_records += 1

            content = _compose_investor_profile(
                person_profile_content,
                track_record_content,
            )
            if insight.exists() and insight.content() == content:
                unchanged += 1
                insights.append(insight)
                continue

            insight.save(content)
            written += 1
            insights.append(insight)
        except Exception as error:
            logger.warning(f"[{dataset_slug}] Skipping {filename}: {error}")
            skipped += 1

    logger.info(
        f"[{dataset_slug}] Investor profiles complete: "
        f"{written} written, {unchanged} unchanged, {skipped} skipped."
    )
    return InvestorProfileResult(
        source_dataset=dataset_slug,
        person_profiles=len(filenames),
        written=written,
        unchanged=unchanged,
        skipped=skipped,
        missing_track_records=missing_track_records,
        insights=insights,
    )


async def investor_profile(
    source_dataset: str = "sictic-members",
) -> InsightResult:
    """Build investor profiles and return their managed insight artifacts."""
    result = await _investor_profile_result(source_dataset)
    return result.insights


def read_investor_profiles(
    source_dataset: str,
    names: List[str],
) -> dict[str, str]:
    """Read the preferred investor-profile model for each requested person."""
    dataset_slug = slugify(source_dataset)
    storage = get_storage()
    profile_dir = f"{dataset_insights_path(dataset_slug)}/investor-profile"
    if not storage.exists(profile_dir):
        return {}

    from lib.people.discovery import persons_in_dataset

    discovered = persons_in_dataset(dataset_slug)
    files = storage.list(profile_dir, suffix=".md")
    files_by_id: dict[str, list[str]] = {}
    for filename in files:
        linkedin_id = insight_base_name(filename)
        if linkedin_id and linkedin_id != PurePosixPath(filename).stem:
            files_by_id.setdefault(linkedin_id, []).append(filename)

    results: dict[str, str] = {}
    for name in names:
        matched = Person(full_name=name, linkedin_id=slugify(name)).find_best_match(discovered)
        if matched is None:
            matched = Person(full_name=name).find_best_match(discovered)
        if matched is None or not matched.linkedin_id:
            logger.warning(f"[{dataset_slug}] No LinkedIn ID found for investor '{name}'.")
            continue

        selected = InsightFile(
            dataset=dataset_slug,
            skill="investor_profile",
            model="manual",
            identifier=matched.linkedin_id,
            subdir=True,
        ).find_any()
        if selected is None:
            logger.warning(f"[{dataset_slug}] No investor profile found for '{name}'.")
            continue
        results[name] = selected.content()

    return results
