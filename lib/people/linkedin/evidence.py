"""Compact factual LinkedIn evidence without changing stored payloads."""

from __future__ import annotations

import json
import re

from lib.people.model import Person


def condense_profile(person: Person, *, company_names: list[str], description_chars: int) -> dict:
    """Keep identity and all employment entries; shorten only descriptions.

    Matches are evidence hints, not affiliation decisions. Unknown payload
    shapes are not interpreted as proof that a person never worked somewhere.
    """
    payload = person.linkedin_profile
    aliases = [re.sub(r"\W+", " ", name.casefold()).strip() for name in company_names if name]

    def compact(value, *, relevant: bool = False):
        if isinstance(value, list):
            return [compact(item, relevant=relevant) for item in value]
        if not isinstance(value, dict):
            return value
        text = re.sub(r"\W+", " ", json.dumps(value, ensure_ascii=False).casefold())
        relevant = relevant or any(f" {alias} " in f" {text} " for alias in aliases if alias)
        result = {}
        for key, item in value.items():
            normalized = key.casefold().replace("_", "")
            if normalized in {"description", "summary"}:
                if relevant and isinstance(item, str):
                    result[key] = item[:description_chars]
            elif normalized in {
                "company", "companyname", "companyid", "companyurl", "companylinkedinurl",
                "title", "position", "name", "startdate", "enddate", "daterange",
                "duration", "totalduration", "timeperiod", "iscurrent", "current",
                "employmenttype", "location", "locationname", "companyuniversalname",
                "year", "month", "day", "text", "start", "end",
                "subtitle", "caption", "metadata",
                "positions", "experiences", "experience", "items",
            }:
                result[key] = compact(item, relevant=relevant)
        return result

    history = {
        key: compact(payload[key])
        for key in ("experiences", "experience", "positions", "workExperience", "workHistory", "currentPosition")
        if payload.get(key)
    }
    return {
        "full_name": person.full_name,
        "linkedin_id": person.linkedin_id,
        "email_addresses": person.email_addresses,
        "headline": payload.get("headline", ""),
        "current_company": compact(payload.get("currentCompany", {})),
        "employment_history": history,
        "employment_history_available": bool(history),
    }
