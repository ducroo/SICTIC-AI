"""Generate SICTIC member person-profile insights, then optionally index them.

The source of truth is the configured community member dataset. Existing skill
code handles the two relevant inputs there: structured LinkedIn cache files and
the broader dataset documents used for dossier/mention context.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional

import typer

from lib.models.person import Person
from lib.slugify import slugify
from lib.storage import get_storage
from lib.storage_domains import dataset_insights_path

try:
    from scripts.sync_person_profiles_from_insights import sync_person_profiles_from_insights
except ModuleNotFoundError:
    # Allows direct execution as `python scripts/generate_member_profiles.py`.
    from sync_person_profiles_from_insights import sync_person_profiles_from_insights

app = typer.Typer(help="Generate SICTIC member person profile insights.")


@dataclass(frozen=True)
class GenerateMemberProfilesResult:
    dataset: str
    requested: int
    generated: int
    indexed: bool


def _parse_names(raw_names: Optional[str]) -> Optional[List[str]]:
    if not raw_names:
        return None
    return [name.strip() for name in raw_names.split(",") if name.strip()]


def _target_people(dataset: str, names: Optional[List[str]], limit: Optional[int]) -> List[Person]:
    from skills.person_profile.persons_in_dataset import persons_in_dataset

    discovered = persons_in_dataset(slugify(dataset))
    if names:
        selected: List[Person] = []
        for name in names:
            requested = Person(full_name=name)
            selected.append(requested.find_best_match(discovered) or requested)
    else:
        selected = discovered

    if limit is not None:
        selected = selected[:limit]
    return selected


def _remove_existing_profile_outputs(dataset: str, people: List[Person]) -> int:
    storage = get_storage()
    profile_dir = f"{dataset_insights_path(dataset)}/person-profile"
    if not storage.exists(profile_dir):
        return 0

    identifiers = {p.identifier for p in people if p.identifier}
    identifiers.update(slugify(p.display_name) for p in people if p.display_name)
    removed = 0

    for filename in storage.list(profile_dir, suffix=".md"):
        if any(filename.startswith(f"person-profile-{identifier}-") for identifier in identifiers):
            storage.remove(f"{profile_dir}/{filename}")
            removed += 1
    return removed


async def generate_member_profiles(
    *,
    dataset: str = "sictic-members",
    names: Optional[List[str]] = None,
    limit: Optional[int] = None,
    force_refresh: bool = False,
    skip_index: bool = False,
    sync_source: bool = False,
    linkedin_only: bool = True,
) -> GenerateMemberProfilesResult:
    if sync_source:
        from skills.dataset_chat.core.ingestion import sync_datasets

        await sync_datasets([dataset], raise_on_error=True, force=True)

    people = _target_people(dataset, names, limit)
    if force_refresh:
        _remove_existing_profile_outputs(dataset, people)

    request_names = [person.display_name for person in people]
    from skills.person_profile.person_profile import person_profile

    generated = await person_profile(
        dataset_name=dataset,
        names=request_names,
        include_dataset_context=not linkedin_only,
    )

    if not skip_index:
        await sync_person_profiles_from_insights(source_dataset=dataset)

    return GenerateMemberProfilesResult(
        dataset=slugify(dataset),
        requested=len(request_names),
        generated=len(generated),
        indexed=not skip_index,
    )


@app.command()
def main(
    dataset: str = typer.Option("sictic-members", "--dataset", help="Community dataset to use as the member source."),
    names: Optional[str] = typer.Option(None, "--names", help="Comma-separated member names or LinkedIn IDs to generate."),
    limit: Optional[int] = typer.Option(None, "--limit", min=1, help="Limit the number of discovered members to process."),
    force_refresh: bool = typer.Option(False, "--force-refresh", help="Remove existing selected profile outputs before generation."),
    skip_index: bool = typer.Option(False, "--skip-index", help="Generate insight files without hydrating/indexing person_profile."),
    sync_source: bool = typer.Option(False, "--sync-source/--no-sync-source", help="Force-sync the source dataset before profile generation."),
    linkedin_only: bool = typer.Option(True, "--linkedin-only/--with-dataset-context", help="Use cached LinkedIn member data only, or also search source dataset context."),
) -> None:
    result = asyncio.run(
        generate_member_profiles(
            dataset=dataset,
            names=_parse_names(names),
            limit=limit,
            force_refresh=force_refresh,
            skip_index=skip_index,
            sync_source=sync_source,
            linkedin_only=linkedin_only,
        )
    )
    typer.echo(f"Dataset: {result.dataset}")
    typer.echo(f"Requested profiles: {result.requested}")
    typer.echo(f"Generated profiles: {result.generated}")
    typer.echo(f"Indexed: {'yes' if result.indexed else 'no'}")


if __name__ == "__main__":
    app()
