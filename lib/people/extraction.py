"""Local candidate extraction; affiliation is decided by the consuming workflow."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from lib.datasets.models import Chunk
from lib.people.linkedin.identity import PROFILE_URL, extract_linkedin_id, extract_linkedin_ids
from lib.people.linkedin.service import sanitize_name
from lib.people.model import Person, extract_email_addresses


def rank_people_by_document_weight(people: list[Person]) -> list[tuple[Person, float]]:
    """Rank merged identities by sum(1 / distinct candidates per document).

    Each person counts once per document, regardless of pages or repetitions.
    Names, email-only identities and LinkedIn IDs share each document. Preserve
    the supplied Person objects and evidence; identity merging remains the caller's job.
    """
    documents: dict[str, set[int]] = defaultdict(set)
    for index, person in enumerate(people):
        if person.identifier:
            for chunk in person.mentions:
                documents[chunk.document_name].add(index)
    scores: dict[int, float] = defaultdict(float)
    for document in sorted(documents):
        members = documents[document]
        for index in members:
            scores[index] += 1 / len(members)
    ranked = [(person, scores[index]) for index, person in enumerate(people)
              if person.identifier]
    return sorted(ranked, key=lambda item: (-item[1], item[0].full_name.casefold(), item[0].identifier))


def merge_person(persons: list[Person], candidate: Person) -> None:
    """Reconcile candidates using the shared identity boundary and merge policy."""
    Person.merge_into(persons, candidate)


class PersonExtractor:
    """Load a local spaCy pipeline once per scan and process bounded chunks."""

    def __init__(self, model: str, *, batch_size: int, nlp=None):
        if nlp is None:
            import spacy
            try:
                nlp = spacy.load(model)
            except OSError as error:
                raise RuntimeError(
                    f"Missing spaCy model {model!r}; install the configured environment before discovery."
                ) from error
        self.nlp = nlp
        self.batch_size = batch_size

    def extract(self, chunks: Iterable[Chunk]) -> list[Person]:
        people: list[Person] = []
        for local, email_candidates in self._candidate_groups(chunks, merge_local=True):
            for person in local:
                merge_person(people, person)
            # Preserve the production rule: extracted emails begin as sparse records.
            for candidate in email_candidates:
                exact = next((person for person in people
                              if person.email_addresses == candidate.email_addresses
                              and not person.full_name and not person.linkedin_id), None)
                if exact is None:
                    people.append(candidate)
                else:
                    exact.merge(candidate)
        return people

    def extract_candidates(self, chunks: Iterable[Chunk]) -> list[Person]:
        """Extract once for merger comparisons, without consolidating candidates.

        Named Markdown-link associations are retained. Production extract() keeps
        its historical local/global merging and sparse-email policy.
        """
        return [person for local, emails in self._candidate_groups(chunks, merge_local=False)
                for person in [*local, *emails]]

    def _candidate_groups(self, chunks: Iterable[Chunk], *, merge_local: bool):
        stream = ((chunk.text, chunk) for chunk in chunks)
        for doc, chunk in self.nlp.pipe(stream, as_tuples=True, batch_size=self.batch_size):
            names = list(dict.fromkeys(
                sanitize_name(entity.text) for entity in doc.ents
                if entity.label_ in {"PERSON", "PER"} and entity.text.strip()
            ))
            local = [Person(full_name=name, mentions=[chunk]) for name in names]
            # Only named Markdown links explicitly associate a name with a URL.
            for label, url in re.findall(r"\[([^\]]+)\]\(([^\s)]+)\)", chunk.text):
                if not PROFILE_URL.fullmatch(url.split("?", 1)[0].rstrip("/")):
                    continue
                named = Person(full_name=label).find_best_match(local)
                if named is not None:
                    candidate = Person(full_name=named.full_name,
                                       linkedin_id=extract_linkedin_id(url), mentions=[chunk])
                    if merge_local:
                        merge_person(local, candidate)
                    else:
                        local.append(candidate)
            for identifier in extract_linkedin_ids(chunk.text):
                candidate = Person(linkedin_id=identifier, mentions=[chunk])
                if merge_local:
                    merge_person(local, candidate)
                else:
                    local.append(candidate)
            yield local, [Person(email_addresses=[email], mentions=[chunk])
                          for email in extract_email_addresses(chunk.text)]
