from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from skills.dd_checks.dd_checks import dd_checks
from skills.dd_priorities.dd_priorities import dd_priorities
from skills.sha_review.sha_review import sha_review
from skills.submission_ready.submission_ready import submission_ready
from skills.expert_search.expert_search import expert_search
from skills.investor_profile.investor_profile import investor_profile
from skills.person_profile.person_profile import person_profile
from skills.persons_in_dataset.persons_in_dataset import persons_in_dataset
from skills.potential_investors.potential_investors import potential_investors
from skills.startup_profile.startup_profile import startup_profile
from skills.startup_traction.startup_traction import startup_traction
from skills.suggested_startups.suggested_startups import suggested_startups
from skills.team_profile.team_profile import team_profile
from skills.team_profile_revised.team_profile_revised import team_profile_revised


SkillCallable = Callable[[str], Awaitable[object]]


@dataclass(frozen=True)
class SkillSpec:
    func: SkillCallable
    domains: frozenset[str]
    depends_on: tuple[str, ...] = ()


SKILL_REGISTRY = {
    "startup-profile": SkillSpec(
        func=startup_profile,
        domains=frozenset({"startups"}),
    ),
    "persons-in-dataset": SkillSpec(
        func=persons_in_dataset,
        domains=frozenset({"startups", "community"}),
    ),
    "person-profile": SkillSpec(
        func=person_profile,
        domains=frozenset({"startups", "community"}),
        depends_on=("persons-in-dataset",),
    ),
    "team-profile": SkillSpec(
        func=team_profile,
        domains=frozenset({"startups"}),
        depends_on=("startup-profile", "person-profile"),
    ),
    "team-profile-revised": SkillSpec(
        func=team_profile_revised,
        domains=frozenset({"startups"}),
        depends_on=("startup-profile", "person-profile"),
    ),
    "startup-traction": SkillSpec(
        func=startup_traction,
        domains=frozenset({"startups"}),
        depends_on=("startup-profile",),
    ),
    "dd-checks": SkillSpec(
        func=dd_checks,
        domains=frozenset({"startups"}),
        depends_on=("startup-profile",),
    ),
    "dd-priorities": SkillSpec(
        func=dd_priorities,
        domains=frozenset({"startups"}),
        depends_on=("dd-checks",),
    ),
    "sha-review": SkillSpec(
        func=sha_review,
        domains=frozenset({"startups"}),
    ),
    "submission-ready": SkillSpec(
        func=submission_ready,
        domains=frozenset({"startups"}),
    ),
    "investor-profile": SkillSpec(
        func=investor_profile,
        domains=frozenset({"community"}),
        depends_on=("person-profile",),
    ),
    "expert-search": SkillSpec(
        func=expert_search,
        domains=frozenset({"startups"}),
        depends_on=("startup-profile", "investor-profile"),
    ),
    "potential-investors": SkillSpec(
        func=potential_investors,
        domains=frozenset({"startups"}),
        depends_on=("startup-profile", "investor-profile"),
    ),
    "suggested-startups": SkillSpec(
        func=suggested_startups,
        domains=frozenset({"community"}),
        depends_on=("startup-profile", "investor-profile"),
    ),
}


def expand_skill_dependencies(target_skills: list[str]) -> list[str]:
    expanded = set()

    def add_with_dependencies(skill_name: str) -> None:
        if skill_name not in SKILL_REGISTRY:
            raise ValueError(f"Unknown bulk refresh skill: {skill_name}")
        if skill_name in expanded:
            return
        for dependency in SKILL_REGISTRY[skill_name].depends_on:
            add_with_dependencies(dependency)
        expanded.add(skill_name)

    for skill_name in target_skills:
        add_with_dependencies(skill_name)
    return [name for name in SKILL_REGISTRY if name in expanded]
