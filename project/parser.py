from __future__ import annotations

"""
HTML parsing and data cleaning utilities for Attijari Bank branch pages.

This module is intentionally independent from any HTTP or browser logic.
It only knows how to:
- Turn raw HTML into structured branch records.
- Clean / normalise text fields.
- Remove duplicate branches.
"""

from dataclasses import dataclass, asdict
from typing import Iterable, List, Dict, Set
import re
import unicodedata

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Branch:
    """Structured representation of a single branch record."""

    name: str
    branch_type: str
    address: str
    postal_code: str
    city: str
    telephone: str
    fax: str
    email: str
    latitude: str
    longitude: str


SPACE_RE = re.compile(r"\s+")
POSTAL_CITY_RE = re.compile(
    r"(?P<postal_code>\d{4})(?:\s+(?P<city>[A-Za-zÀ-ÖØ-öø-ÿ' -]+))?$"
)
LEADING_TYPE_RE = re.compile(
    r"^(?P<branch_type>AGENCE|CENTRE D'AFFAIRES|CENTRE AFFAIRES|POINT DE VENTE)\s+",
    re.IGNORECASE,
)


def _normalise_text(value: str) -> str:
    """
    Clean a text field:
    - strip leading / trailing whitespace
    - collapse internal whitespace to a single space
    - normalise Unicode so French accents are consistent
    """
    if not value:
        return ""

    stripped = value.strip()
    collapsed = SPACE_RE.sub(" ", stripped)
    normalised = unicodedata.normalize("NFKC", collapsed)
    return normalised


def clean_branch(raw: Dict[str, str]) -> Branch:
    """Apply `_normalise_text` to all branch fields and build a Branch object."""
    return Branch(
        name=_normalise_text(raw.get("name", "")),
        branch_type=_normalise_text(raw.get("branch_type", "")),
        address=_normalise_text(raw.get("address", "")),
        postal_code=_normalise_text(raw.get("postal_code", "")),
        city=_normalise_text(raw.get("city", "")),
        telephone=_normalise_text(raw.get("telephone", "")),
        fax=_normalise_text(raw.get("fax", "")),
        email=_normalise_text(raw.get("email", "")),
        latitude=_normalise_text(raw.get("latitude", "")),
        longitude=_normalise_text(raw.get("longitude", "")),
    )


def branches_to_dicts(branches: Iterable[Branch]) -> List[Dict[str, str]]:
    """Convert a list of Branch instances into a list of plain dictionaries."""
    return [asdict(b) for b in branches]


def deduplicate_branches(branches: Iterable[Branch]) -> List[Branch]:
    """
    Remove duplicate branches.

    We treat branches as duplicates if they share the same
    (name, address, postal_code, city) tuple.
    """
    unique: List[Branch] = []
    seen: Set[tuple] = set()

    for b in branches:
        key = (b.name.lower(), b.address.lower(), b.postal_code.lower(), b.city.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(b)

    return unique


def _extract_text_or_empty(parent, selector: str) -> str:
    """
    Helper to read text from a nested element.
    Returns an empty string if the element is missing.
    """
    if parent is None:
        return ""
    tag = parent.select_one(selector)
    if tag is None:
        return ""
    return tag.get_text(separator=" ", strip=True)


def _extract_label_value(container, label_prefixes: tuple[str, ...]) -> str:
    """
    Find a paragraph whose text begins with one of the given labels and return its value.
    """
    for paragraph in container.select("p"):
        text = paragraph.get_text(separator=" ", strip=True)
        lowered = text.lower()
        for prefix in label_prefixes:
            if lowered.startswith(prefix.lower()):
                parts = text.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip()
                return text
    return ""


def _split_branch_type(name: str) -> tuple[str, str]:
    """
    Infer a branch type from the start of the branch name.
    Example: 'AGENCE ZAGHOUANE' -> ('Agence', 'ZAGHOUANE')
    """
    match = LEADING_TYPE_RE.match(name.strip())
    if not match:
        return "", name.strip()

    branch_type = match.group("branch_type").title()
    cleaned_name = name[match.end() :].strip(" -")
    return branch_type, cleaned_name


def _extract_postal_code_and_city(address: str) -> tuple[str, str]:
    """
    Extract postal code and city from the tail of the address if present.

    Typical examples from the Attijari page:
    - 'Angle 63 Avenue Jugurtha..., 1082 Tunis'
    - 'AVENUE DE L'INDEPENDANCE, 1100'
    - '17 Avenue Habib Bourguiba- Tunis, 1000'
    """
    if not address:
        return "", ""

    normalized = address.replace("–", "-")
    parts = [part.strip(" -") for part in normalized.split(",") if part.strip()]
    if not parts:
        return "", ""

    # First try the final comma-separated segment, e.g. "1082 Tunis" or "1100".
    last_part = parts[-1]
    match = POSTAL_CITY_RE.search(last_part)
    if match:
        postal_code = match.group("postal_code") or ""
        city = (match.group("city") or "").strip()

        # If the city is not in the final segment, try the preceding segment tail.
        if not city and len(parts) >= 2:
            previous = parts[-2]
            if "-" in previous:
                city = previous.split("-")[-1].strip()
        return postal_code, city

    # Fallback: scan the whole address for the last 4-digit postal code.
    postal_matches = list(re.finditer(r"\b\d{4}\b", normalized))
    postal_code = postal_matches[-1].group(0) if postal_matches else ""

    city = ""
    if "-" in normalized:
        city = normalized.split("-")[-1].strip()
        city = re.sub(r"\b\d{4}\b.*$", "", city).strip(" ,")

    return postal_code, city


def parse_branches_from_html(html: str) -> List[Dict[str, str]]:
    """
    Parse a branch listing page and return raw branch dictionaries.

    NOTE:
      The exact HTML structure of the Attijari directory can change.
      This parser targets common patterns:
        - each branch contained in a block element with a specific class
        - fields labelled by CSS classes or headings
      Adjust the selectors here if the site layout changes.
    """
    soup = BeautifulSoup(html, "lxml")

    # Target the actual geolocation branch cards used by the site.
    containers = soup.select("div.geolocation-location")
    if not containers:
        # Fallback to the older generic selectors if the site structure changes.
        containers = soup.select(".views-row, .branch-item, .agence-item, .agences-item")

    results: List[Dict[str, str]] = []

    for container in containers:
        # Branch name is stored in the visible title inside the map card.
        raw_name = _extract_text_or_empty(container, ".header-map .title, h2.title, h2")
        branch_type, name = _split_branch_type(raw_name)
        if not name:
            continue

        # Read labeled fields from the branch content block.
        address = _extract_label_value(
            container, ("Adresse :", "Adresse")
        )
        telephone = _extract_label_value(
            container, ("Téléphone :", "Telephone :", "Téléphone", "Telephone")
        )
        fax = _extract_label_value(
            container, ("Fax:", "Fax :")
        )
        email = _extract_label_value(
            container, ("Mail Agence:", "Mail Agence :", "Email :", "Email")
        )

        # Prefer the actual link value for email if present.
        email_link = container.select_one("a[href^='mailto:']")
        if email_link is not None:
            email = email_link.get_text(strip=True)

        postal_code, city = _extract_postal_code_and_city(address)

        # Co-ordinates are often stored in data attributes or hidden fields.
        latitude = str(
            container.get("data-latitude")
            or container.get("data-lat")
            or ""
        )
        longitude = str(
            container.get("data-longitude")
            or container.get("data-lng")
            or container.get("data-lon")
            or ""
        )

        # Fallback: search for hidden inputs.
        if not latitude:
            lat_input = container.select_one("input[name*='lat']")
            if lat_input is not None:
                latitude = lat_input.get("value", "")

        if not longitude:
            lon_input = container.select_one("input[name*='lon'], input[name*='lng']")
            if lon_input is not None:
                longitude = lon_input.get("value", "")

        results.append(
            {
                "name": name,
                "branch_type": branch_type,
                "address": address,
                "postal_code": postal_code,
                "city": city,
                "telephone": telephone,
                "fax": fax,
                "email": email,
                "latitude": latitude,
                "longitude": longitude,
            }
        )

    return results

