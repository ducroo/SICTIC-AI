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
    """Rank already-merged names by sum(1 / distinct names in each document).

    Each person counts once per document, regardless of pages or repetitions.
    Contact-only candidates do not dilute the name weights. Preserve the supplied
    Person objects and their evidence; identity merging remains the caller's job.
    """
    documents: dict[str, set[int]] = defaultdict(set)
    for index, person in enumerate(people):
        if person.full_name.strip():
            for chunk in person.mentions:
                documents[chunk.document_name].add(index)
    scores: dict[int, float] = defaultdict(float)
    for document in sorted(documents):
        members = documents[document]
        for index in members:
            scores[index] += 1 / len(members)
    ranked = [(person, scores[index]) for index, person in enumerate(people)
              if person.full_name.strip()]
    return sorted(ranked, key=lambda item: (-item[1], item[0].full_name.casefold(), item[0].identifier))


def merge_person(persons: list[Person], candidate: Person) -> None:
    """Reconcile candidates using the shared identity boundary and merge policy."""
    existing = candidate.find_best_match(persons)
    if existing is None:
        persons.append(candidate)
        return
    existing.merge(candidate)
    for other in list(persons):
        if other is not existing and existing.matches(other):
            existing.merge(other)
            persons.remove(other)


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
                    merge_person(local, Person(full_name=named.full_name,
                                              linkedin_id=extract_linkedin_id(url), mentions=[chunk]))
            for identifier in extract_linkedin_ids(chunk.text):
                merge_person(local, Person(linkedin_id=identifier, mentions=[chunk]))
            # Emails start as sparse candidates; the final review verifies associations.
            for person in local:
                merge_person(people, person)
            for email in extract_email_addresses(chunk.text):
                exact = next((person for person in people if person.email_addresses == [email]
                              and not person.full_name and not person.linkedin_id), None)
                candidate = Person(email_addresses=[email], mentions=[chunk])
                if exact is None:
                    people.append(candidate)
                else:
                    exact.merge(candidate)
        return people
