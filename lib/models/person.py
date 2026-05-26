from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any
from rapidfuzz import fuzz
from lib.slugify import slugify
from skills.dataset_chat.core.models import Chunk

@dataclass
class Person:
    full_name: str = ""
    linkedinID: str = ""
    linkedin_profile: Dict[str, Any] = field(default_factory=dict)
    dossier: List[Chunk] = field(default_factory=list)
    mentions: List[Chunk] = field(default_factory=list)
    person_profile: str = ""

    @property
    def identifier(self) -> str:
        """Returns the canonical ID, falling back to a slugified name."""
        return self.linkedinID if self.linkedinID else slugify(self.full_name)

    @property
    def display_name(self) -> str:
        """Returns the best human-readable name."""
        return self.full_name if self.full_name else self.linkedinID

    def match_score(self, other: 'Person') -> int:
        """
        Returns a 0-100 score indicating how closely this person matches another.
        """
        # 1. Exact ID Match (Strongest signal)
        if self.linkedinID and other.linkedinID:
            if self.linkedinID.lower() == other.linkedinID.lower():
                return 100
                
        # 2. Name Match (Exact or Substring)
        if self.full_name and other.full_name:
            n1, n2 = self.full_name.lower(), other.full_name.lower()
            if n1 == n2 or n1 in n2 or n2 in n1:
                return 100
            
            # Fuzzy match score
            score = fuzz.token_sort_ratio(n1, n2)
            if score > 0:
                return score
                
        # 3. Cross-match Fallback (ID vs Name)
        if self.linkedinID and other.full_name:
            if slugify(other.full_name) in self.linkedinID.lower():
                return 100
        if other.linkedinID and self.full_name:
            if slugify(self.full_name) in other.linkedinID.lower():
                return 100
                
        # 4. Strict Identifier Fallback
        id1, id2 = self.identifier.lower(), other.identifier.lower()
        if id1 and id2 and id1 == id2:
            return 100
            
        return 0

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
            
        if not self.linkedinID and other.linkedinID:
            self.linkedinID = other.linkedinID
            
        if not self.linkedin_profile and other.linkedin_profile:
            self.linkedin_profile = other.linkedin_profile
            
        if not self.person_profile and other.person_profile:
            self.person_profile = other.person_profile
            
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

    def to_dict(self) -> dict:
        """For JSON serialization/caching."""
        data = asdict(self)
        data['dossier'] = [c.dict() if hasattr(c, 'dict') else c for c in self.dossier]
        data['mentions'] = [c.dict() if hasattr(c, 'dict') else c for c in self.mentions]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'Person':
        """Safely loads from JSON cache, ignoring unexpected keys."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        
        # Hydrate Chunks
        if 'dossier' in filtered_data and isinstance(filtered_data['dossier'], list):
            filtered_data['dossier'] = [Chunk(**c) if isinstance(c, dict) else c for c in filtered_data['dossier']]
        if 'mentions' in filtered_data and isinstance(filtered_data['mentions'], list):
            filtered_data['mentions'] = [Chunk(**c) if isinstance(c, dict) else c for c in filtered_data['mentions']]
            
        return cls(**filtered_data)
