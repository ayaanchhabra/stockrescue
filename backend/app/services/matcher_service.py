"""Candidate matcher: links Qloo-related entities to products the shop stocks.

Qloo may return entities the shop does not sell. Only stocked products can form
a bundle, so this module answers: "which of OUR products connect to what Qloo
returned, and how strongly?"

Each link is labelled with how it was made (values match MatchKind in
schemas/rescue.py):

  exact       same Qloo entity id, or the same title after normalising case,
              accents, punctuation, "&" and a leading "The/A/An".
  fuzzy       similar title (or the same main title with a different subtitle),
              or the same creator as the Qloo entity. A different work may be
              involved, so a human should confirm it.
  theme_only  connected only through a shared genre or theme tag.

These labels are OUR internal evidence strength. They are never presented as a
Qloo score. A link is a hypothesis generator, not proof that anything will sell.

Input shapes
------------
`QlooRelatedEntity` and `StockItem` are this module's own plain inputs so the
matcher can be built and tested before the real Qloo models (P1) and inventory
functions (P4) exist. When those arrive, write one small adapter that builds
these objects from them; the matching rules below should not need to change.
No Qloo field names are assumed here.

Pure Python: no pydantic, no network.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .constraints_service import ProductRef
from .rescue_config import DEFAULT_MATCH_SETTINGS, MatchSettings

# Match kinds (same values as MatchKind in schemas/rescue.py)
EXACT = "exact"
FUZZY = "fuzzy"
THEME_ONLY = "theme_only"

_KIND_RANK: Dict[str, int] = {EXACT: 0, FUZZY: 1, THEME_ONLY: 2}

# Internal similarity (0..1) used only to order links of the same kind.
_CREATOR_SIMILARITY = 0.8
_MAIN_TITLE_SIMILARITY = 0.9


# ---------------------------------------------------------------------------
# Inputs and outputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QlooRelatedEntity:
    """One entity Qloo returned as related to the slow product."""

    entity_id: str
    name: str
    entity_type: Optional[str] = None
    creators: Tuple[str, ...] = ()   # authors/directors etc., if Qloo supplied them
    tags: Tuple[str, ...] = ()       # genres/themes, if Qloo supplied them
    raw_ref: Optional[str] = None    # pointer to the stored raw response (provenance)
    qloo_affinity: Optional[float] = None  # Qloo query.affinity; NULL stays NULL
    source_entity_id: Optional[str] = None
    source_entity_type: Optional[str] = None
    evidence_id: Optional[int] = None
    request_params: Optional[dict] = None
    fetched_at: Optional[str] = None


@dataclass(frozen=True)
class StockItem:
    """A stocked product plus the descriptive fields the matcher needs."""

    product: ProductRef
    creators: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    qloo_entity_id: Optional[str] = None  # set when the shop's item is already mapped


@dataclass(frozen=True)
class CandidateMatch:
    """One stocked product linked to one Qloo entity."""

    product: ProductRef
    match_kind: str          # "exact" | "fuzzy" | "theme_only"
    entity: QlooRelatedEntity
    reason: str              # plain-language explanation of how the link was made
    similarity: float        # internal 0..1, only used to order links of one kind


def match_sort_key(m: CandidateMatch) -> tuple:
    """Strongest link first; ties broken by similarity, then names (deterministic)."""
    return (
        _KIND_RANK[m.match_kind],
        -m.similarity,
        m.product.name.casefold(),
        m.entity.name.casefold(),
        m.entity.entity_id,
    )


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _drop_apostrophes(text: str) -> str:
    """"Midnight's" and "Midnights" should compare equal, so remove apostrophes."""
    return text.replace("'", "").replace("\u2019", "").replace("\u2018", "")


def normalize_title(title: str) -> str:
    """Lower-case, accent-free, punctuation-free title without a leading article."""
    text = _strip_accents(title or "").casefold().replace("&", " and ")
    text = _drop_apostrophes(text)
    text = re.sub(r"[^\w\s]", " ", text).replace("_", " ")
    tokens = text.split()
    if len(tokens) > 1 and tokens[0] in {"the", "a", "an"}:
        tokens = tokens[1:]
    return " ".join(tokens)


def _main_title(title: str) -> str:
    """Normalised title before a subtitle separator (':' or a spaced dash)."""
    return normalize_title(re.split(r"\s*[:—–]\s*|\s+-\s+", title or "", maxsplit=1)[0])


_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def normalize_name(name: str) -> str:
    """Normalise a person's name: 'Rowling, J. K.' and 'JK Rowling' compare equal."""
    text = _strip_accents(name or "").casefold()
    if text.count(",") == 1:
        last, first = (part.strip() for part in text.split(","))
        if first.strip(". ") not in _NAME_SUFFIXES and first and last:
            text = f"{first} {last}"
    text = _drop_apostrophes(text)
    text = re.sub(r"[^\w\s]", " ", text).replace("_", " ")
    out: List[str] = []
    initials = ""
    for token in text.split():
        if len(token) == 1:
            initials += token  # join "j k" -> "jk"
        else:
            if initials:
                out.append(initials)
                initials = ""
            out.append(token)
    if initials:
        out.append(initials)
    return " ".join(out)


def normalize_tag(tag: str) -> str:
    text = _strip_accents(tag or "").casefold().replace("-", " ").replace("_", " ")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def title_similarity(a: str, b: str) -> float:
    """0..1 similarity of two normalised titles (internal use)."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return round(SequenceMatcher(None, na, nb).ratio(), 4)


# ---------------------------------------------------------------------------
# Matching one stocked item against one Qloo entity
# ---------------------------------------------------------------------------

def _match_one(
    item: StockItem, entity: QlooRelatedEntity, settings: MatchSettings
) -> Optional[CandidateMatch]:
    name = item.product.name

    # 1. exact: same Qloo entity id
    if item.qloo_entity_id and item.qloo_entity_id == entity.entity_id:
        return CandidateMatch(
            item.product, EXACT, entity,
            f"'{name}' is already mapped to Qloo entity id {entity.entity_id}.", 1.0,
        )

    # 1b. exact: same normalised title
    norm_item, norm_entity = normalize_title(name), normalize_title(entity.name)
    if norm_item and norm_item == norm_entity:
        return CandidateMatch(
            item.product, EXACT, entity,
            f"'{name}' has the same title as the Qloo entity '{entity.name}'.", 1.0,
        )

    # 2a. fuzzy: similar title, or same main title with a different subtitle
    sim = title_similarity(name, entity.name)
    if sim >= settings.fuzzy_title_threshold:
        return CandidateMatch(
            item.product, FUZZY, entity,
            f"The title of '{name}' is similar to the Qloo entity '{entity.name}' "
            f"(similarity {sim:.0%}); confirm it is the same work.", sim,
        )
    main_item, main_entity = _main_title(name), _main_title(entity.name)
    if main_item and main_item == main_entity:
        return CandidateMatch(
            item.product, FUZZY, entity,
            f"'{name}' and the Qloo entity '{entity.name}' share a main title but differ "
            f"in the subtitle; confirm it is the same work.", _MAIN_TITLE_SIMILARITY,
        )

    # 2b. fuzzy: same creator (a different work by the same person)
    entity_people = {normalize_name(c): c for c in (*entity.creators, entity.name)}
    entity_people.pop("", None)
    for creator in item.creators:
        key = normalize_name(creator)
        if key and key in entity_people:
            return CandidateMatch(
                item.product, FUZZY, entity,
                f"'{name}' is by {creator}, who is also linked to the Qloo entity "
                f"'{entity.name}'. It is a different work, so confirm the link is relevant.",
                _CREATOR_SIMILARITY,
            )

    # 3. theme only: shared genre/theme tag
    item_tags = {normalize_tag(t) for t in item.tags} - {""}
    entity_tags = {normalize_tag(t) for t in entity.tags} - {""}
    shared = sorted(item_tags & entity_tags)
    if shared:
        jaccard = len(shared) / len(item_tags | entity_tags)
        return CandidateMatch(
            item.product, THEME_ONLY, entity,
            f"'{name}' shares the theme(s) {', '.join(shared)} with the Qloo entity "
            f"'{entity.name}'; this is a weak, theme-level link.", round(jaccard, 4),
        )

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_candidates(
    entities: Iterable[QlooRelatedEntity],
    stock: Iterable[StockItem],
    exclude_product_ids: Iterable[str] = (),
    settings: MatchSettings = DEFAULT_MATCH_SETTINGS,
) -> List[CandidateMatch]:
    """Every (stocked product, Qloo entity) link, strongest first.

    - `exclude_product_ids`: products that must never be returned, normally the
      slow product itself (it cannot be its own bundle partner).
    - Entities without an id are ignored: Qloo-sourced evidence must always be
      traceable to an entity id.
    - Stock-level checks (quantity, restrictions, margin) are NOT done here; the
      constraint engine rejects those and keeps the reason visible.
    - One product can link to several entities; all links are kept.
    """
    excluded = set(exclude_product_ids)
    usable = [e for e in entities if e.entity_id and e.name]
    matches: List[CandidateMatch] = []
    seen: set = set()
    for item in stock:
        pid = item.product.product_id
        if pid in excluded or pid in seen:
            continue
        seen.add(pid)  # same product listed twice in the input is matched once
        for entity in usable:
            m = _match_one(item, entity, settings)
            if m is not None:
                matches.append(m)
    matches.sort(key=match_sort_key)
    return matches


def best_match_per_product(matches: Sequence[CandidateMatch]) -> List[CandidateMatch]:
    """The strongest link for each product, strongest first."""
    best: Dict[str, CandidateMatch] = {}
    for m in sorted(matches, key=match_sort_key):
        best.setdefault(m.product.product_id, m)
    return sorted(best.values(), key=match_sort_key)
