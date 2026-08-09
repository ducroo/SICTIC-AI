"""Person identity, matching, merging, and serialization."""

from dataclasses import dataclass, field
import re
from typing import Dict, List, Any, Iterable
from rapidfuzz import fuzz
from lib.slugify import slugify
from lib.datasets.models import Chunk
from lib.linkedin_ids import normalize_linkedin_id

EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def normalize_email_addresses(values: str | Iterable[str] | None) -> List[str]:
    if not values:
        return []

    candidates: List[str] = []
    if isinstance(values, str):
        candidates.extend(EMAIL_PATTERN.findall(values))
    else:
        for value in values:
            if value:
                candidates.extend(EMAIL_PATTERN.findall(value))

    normalized: List[str] = []
    seen = set()
    for candidate in candidates:
        email = candidate.strip().removeprefix("mailto:").lower()
        if email and email not in seen:
            normalized.append(email)
            seen.add(email)
    return normalized


def extract_email_addresses(data: Any) -> List[str]:
    if isinstance(data, str):
        return normalize_email_addresses(data)
    if isinstance(data, dict):
        emails: List[str] = []
        for value in data.values():
            emails.extend(extract_email_addresses(value))
        return normalize_email_addresses(emails)
    if isinstance(data, list):
        emails: List[str] = []
        for item in data:
            emails.extend(extract_email_addresses(item))
        return normalize_email_addresses(emails)
    return []


def _email_local_part_score(full_name: str, emails: List[str]) -> int:
    if not full_name or not emails:
        return 0

    name = slugify(full_name).replace("-", " ")
    best = 0
    for email in emails:
        local_part = email.split("@", 1)[0]
        candidate = re.sub(r"[._+\-]+", " ", local_part)
        best = max(best, fuzz.token_sort_ratio(name, candidate))
    return best if best >= 90 else 0


@dataclass
class Person:
    full_name: str = ""
    linkedin_id: str = ""
    email_addresses: List[str] = field(default_factory=list)
    linkedin_profile: Dict[str, Any] = field(default_factory=dict)
    dossier: List[Chunk] = field(default_factory=list)
    mentions: List[Chunk] = field(default_factory=list)
    person_profile_markdown: str = ""

    def __post_init__(self) -> None:
        self.linkedin_id = normalize_linkedin_id(self.linkedin_id)
        self.email_addresses = normalize_email_addresses(self.email_addresses)

    @property
    def identifier(self) -> str:
        """Returns the canonical ID, falling back to email or a slugified name."""
        if self.linkedin_id:
            return self.linkedin_id
        if self.email_addresses:
            return self.email_addresses[0]
        return slugify(self.full_name)

    @property
    def display_name(self) -> str:
        """Returns the best human-readable name."""
        if self.full_name:
            return self.full_name
        if self.linkedin_id:
            return self.linkedin_id
        return self.email_addresses[0] if self.email_addresses else ""

    def match_score(self, other: 'Person') -> int:
        """
        Returns a 0-100 score indicating how closely this person matches another.
        """
        # 1. LinkedIn ID is unique: different IDs are a hard non-match.
        if self.linkedin_id and other.linkedin_id:
            return 100 if self.linkedin_id == other.linkedin_id else 0

        # 2. Email overlap is the next strongest signal.
        if self.email_addresses and other.email_addresses:
            if set(self.email_addresses) & set(other.email_addresses):
                return 100

        # 3. Name Match (Exact, Substring, or Fuzzy)
        if self.full_name and other.full_name:
            n1, n2 = self.full_name.lower(), other.full_name.lower()
            if n1 == n2 or n1 in n2 or n2 in n1:
                return 100
            
            score = fuzz.token_sort_ratio(n1, n2)
            if score > 0:
                return score

        # 4. If only one side has a name, compare it to email local parts.
        return max(
            _email_local_part_score(self.full_name, other.email_addresses),
            _email_local_part_score(other.full_name, self.email_addresses),
        )

    def matches(self, other: 'Person', threshold: int = 85) -> bool:
        """Determines if two Person objects represent the same individual (1-to-1 equivalence)."""
        return self.match_score(other) >= threshold
        
    def find_best_match(self, candidates: List['Person'], threshold: int = 85) -> 'Person | None':
        """Returns the best matching Person from a list of candidates, or None if no match meets the threshold."""
        best_match = None
        highest_score = 0
        
        for candidate in candidates:
            score = self.match_score(candidate)
            if score >= threshold and score > highest_score:
                highest_score = score
                best_match = candidate
                # Early exit for perfect matches
                if score == 100:
                    return best_match
                    
        return best_match

    def merge(self, other: 'Person') -> None:
        """Merges missing or richer attributes from another Person object into this one."""
        # Prefer longer, more complete names ("Johannes Aicher" > "J. Aicher")
        if not self.full_name and other.full_name:
            self.full_name = other.full_name
        elif self.full_name and other.full_name and len(other.full_name) > len(self.full_name):
            self.full_name = other.full_name
            
        if not self.linkedin_id and other.linkedin_id:
            self.linkedin_id = other.linkedin_id

        self.email_addresses = normalize_email_addresses(self.email_addresses + other.email_addresses)
            
        if not self.linkedin_profile and other.linkedin_profile:
            self.linkedin_profile = other.linkedin_profile
            
        if not self.person_profile_markdown and other.person_profile_markdown:
            self.person_profile_markdown = other.person_profile_markdown
            
        # Merge dictionary/list data
        if other.dossier:
            existing_dossier = {c.document_name for c in self.dossier}
            for c in other.dossier:
                if c.document_name not in existing_dossier:
                    self.dossier.append(c)
                    existing_dossier.add(c.document_name)
                    
        if other.mentions:
            existing_mentions = { (c.document_name, c.page_number) for c in self.mentions }
            for c in other.mentions:
                if (c.document_name, c.page_number) not in existing_mentions:
                    self.mentions.append(c)
                    existing_mentions.add((c.document_name, c.page_number))
