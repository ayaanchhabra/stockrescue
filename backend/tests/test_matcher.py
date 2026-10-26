from app.services.constraints_service import ProductRef
from app.services.matcher_service import (
    EXACT,
    FUZZY,
    THEME_ONLY,
    CandidateMatch,
    QlooRelatedEntity,
    StockItem,
    best_match_per_product,
    match_candidates,
    normalize_name,
    normalize_tag,
    normalize_title,
    title_similarity,
)
from app.services.rescue_config import MatchSettings

# --- illustrative test fixtures (NOT real Qloo data) --------------------------
# The entities below are hand-made stand-ins for what the Qloo service might
# return. They exist only to test the matching rules in isolation.


def item(pid, name, qty=5, creators=(), tags=(), qloo_entity_id=None):
    product = ProductRef(pid, name, quantity=qty, unit_cost=200, selling_price=400)
    return StockItem(product, tuple(creators), tuple(tags), qloo_entity_id)


def entity(eid, name, creators=(), tags=(), etype="book"):
    return QlooRelatedEntity(eid, name, etype, tuple(creators), tuple(tags), f"raw/{eid}")


def kinds(matches):
    return [(m.product.product_id, m.match_kind) for m in matches]


# --- normalisation -------------------------------------------------------------

def test_normalize_title_ignores_case_accents_punctuation_and_leading_article():
    assert normalize_title("The Remains of the Day") == "remains of the day"
    assert normalize_title("  Pride & Prejudice! ") == "pride and prejudice"
    assert normalize_title("Café Society") == "cafe society"
    assert normalize_title("Midnight’s Children") == normalize_title("Midnights Children")


def test_normalize_title_keeps_a_one_word_title_that_is_an_article():
    assert normalize_title("The") == "the"


def test_normalize_title_of_empty_or_none_is_empty():
    assert normalize_title("") == ""
    assert normalize_title(None) == ""


def test_normalize_name_handles_order_and_initials():
    assert normalize_name("Murakami, Haruki") == normalize_name("Haruki Murakami")
    assert normalize_name("J. K. Rowling") == normalize_name("JK Rowling")
    assert normalize_name("Rowling, J.K.") == normalize_name("J K Rowling")


def test_normalize_name_does_not_flip_a_suffix():
    assert normalize_name("Martin Luther King, Jr.") == "martin luther king jr"


def test_normalize_tag_unifies_separators():
    assert normalize_tag("Coming-of-Age") == normalize_tag("coming of age")


def test_title_similarity_bounds():
    assert title_similarity("Same Title", "same title") == 1.0
    assert title_similarity("", "anything") == 0.0
    assert 0 < title_similarity("Kafka on the Shore", "Kafka on the Shores") < 1


# --- exact matches ---------------------------------------------------------------

def test_exact_match_on_same_title_despite_formatting():
    m = match_candidates(
        [entity("e1", "Pride & Prejudice")], [item("B2", "pride and prejudice")]
    )
    assert kinds(m) == [("B2", EXACT)]
    assert m[0].entity.entity_id == "e1"
    assert m[0].similarity == 1.0
    assert "same title" in m[0].reason


def test_exact_match_on_stored_qloo_entity_id_even_if_titles_differ():
    m = match_candidates(
        [entity("e9", "Completely Different Name")],
        [item("B2", "Local Edition Title", qloo_entity_id="e9")],
    )
    assert kinds(m) == [("B2", EXACT)]
    assert "e9" in m[0].reason


# --- fuzzy matches ---------------------------------------------------------------

def test_fuzzy_match_on_a_typo_like_difference():
    m = match_candidates([entity("e1", "Kafka on the Shore")], [item("B2", "Kafka on the Shores")])
    assert kinds(m) == [("B2", FUZZY)]
    assert "confirm" in m[0].reason


def test_fuzzy_match_when_only_the_subtitle_differs():
    m = match_candidates([entity("e1", "Wolf Hall")], [item("B2", "Wolf Hall: A Novel")])
    assert kinds(m) == [("B2", FUZZY)]


def test_one_word_prefix_is_not_a_match():
    # "Dune" and "Dune Messiah" are different books; sharing a word is not enough.
    assert match_candidates([entity("e1", "Dune")], [item("B2", "Dune Messiah")]) == []


def test_fuzzy_match_on_shared_creator_with_different_work():
    m = match_candidates(
        [entity("e1", "Norwegian Wood", creators=["Haruki Murakami"])],
        [item("B2", "Kafka on the Shore", creators=["Murakami, Haruki"])],
    )
    assert kinds(m) == [("B2", FUZZY)]
    assert "different work" in m[0].reason
    assert m[0].similarity < 1.0


def test_fuzzy_match_when_the_qloo_entity_is_the_creator():
    m = match_candidates(
        [entity("e1", "Haruki Murakami", etype="person")],
        [item("B2", "Kafka on the Shore", creators=["Haruki Murakami"])],
    )
    assert kinds(m) == [("B2", FUZZY)]


def test_threshold_is_configurable():
    ents = [entity("e1", "Kafka on the Shore")]
    stock = [item("B2", "Kafka on the Shores")]
    strict = MatchSettings(fuzzy_title_threshold=1.0)
    assert match_candidates(ents, stock, settings=strict) == []


def test_invalid_threshold_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        MatchSettings(fuzzy_title_threshold=0)
    with pytest.raises(ValueError):
        MatchSettings(fuzzy_title_threshold=1.5)


# --- theme-only matches ----------------------------------------------------------

def test_theme_only_match_on_shared_tag():
    m = match_candidates(
        [entity("e1", "Some Other Book", tags=["Coming-of-Age", "Japan"])],
        [item("B2", "Unrelated Title", tags=["coming of age"])],
    )
    assert kinds(m) == [("B2", THEME_ONLY)]
    assert "coming of age" in m[0].reason
    assert 0 < m[0].similarity <= 1


def test_no_shared_tag_and_no_other_link_means_no_match():
    m = match_candidates(
        [entity("e1", "Some Other Book", tags=["history"])],
        [item("B2", "Unrelated Title", tags=["cooking"])],
    )
    assert m == []


def test_missing_tags_never_create_a_theme_match():
    assert match_candidates([entity("e1", "X Book")], [item("B2", "Y Book", tags=["history"])]) == []
    assert match_candidates([entity("e1", "X Book", tags=["history"])], [item("B2", "Y Book")]) == []


# --- ordering, exclusions and edge cases ----------------------------------------

def test_strongest_link_comes_first():
    ents = [entity("e1", "Alpha Book", tags=["history"])]
    stock = [
        item("T", "Theme Match", tags=["history"]),
        item("F", "Alpha Bok"),
        item("E", "Alpha Book"),
    ]
    assert [m.match_kind for m in match_candidates(ents, stock)] == [EXACT, FUZZY, THEME_ONLY]


def test_target_product_is_excluded():
    ents = [entity("e1", "Slow Literary Novel")]
    stock = [item("B1", "Slow Literary Novel"), item("B2", "Slow Literary Novel")]
    m = match_candidates(ents, stock, exclude_product_ids=["B1"])
    assert [x.product.product_id for x in m] == ["B2"]


def test_entities_without_an_id_are_ignored():
    m = match_candidates([entity("", "Pride and Prejudice")], [item("B2", "Pride and Prejudice")])
    assert m == []


def test_out_of_stock_items_are_still_matched():
    # Stock checks belong to the constraint engine, which keeps the reason visible.
    m = match_candidates([entity("e1", "Alpha Book")], [item("B2", "Alpha Book", qty=0)])
    assert kinds(m) == [("B2", EXACT)]


def test_product_listed_twice_is_matched_once():
    m = match_candidates(
        [entity("e1", "Alpha Book")], [item("B2", "Alpha Book"), item("B2", "Alpha Book")]
    )
    assert len(m) == 1


def test_one_product_can_link_to_several_entities():
    ents = [entity("e1", "Alpha Book"), entity("e2", "Other", tags=["history"])]
    m = match_candidates(ents, [item("B2", "Alpha Book", tags=["history"])])
    assert sorted(x.entity.entity_id for x in m) == ["e1", "e2"]


def test_best_match_per_product_keeps_the_strongest_link():
    ents = [entity("e1", "Alpha Book"), entity("e2", "Other", tags=["history"])]
    stock = [item("B2", "Alpha Book", tags=["history"]), item("B3", "Zed", tags=["history"])]
    best = best_match_per_product(match_candidates(ents, stock))
    assert [(m.product.product_id, m.match_kind) for m in best] == [("B2", EXACT), ("B3", THEME_ONLY)]


def test_result_is_deterministic_regardless_of_input_order():
    ents = [entity("e1", "Alpha Book", tags=["history"]), entity("e2", "Beta", tags=["history"])]
    stock = [item("B2", "Gamma", tags=["history"]), item("B3", "Delta", tags=["history"])]
    a = match_candidates(ents, stock)
    b = match_candidates(list(reversed(ents)), list(reversed(stock)))
    assert [(m.product.product_id, m.entity.entity_id) for m in a] == [
        (m.product.product_id, m.entity.entity_id) for m in b
    ]


def test_empty_inputs_give_no_matches():
    assert match_candidates([], [item("B2", "Alpha")]) == []
    assert match_candidates([entity("e1", "Alpha")], []) == []


def test_match_carries_provenance_for_the_evidence_panel():
    m = match_candidates([entity("e1", "Alpha Book")], [item("B2", "Alpha Book")])[0]
    assert isinstance(m, CandidateMatch)
    assert m.entity.entity_id == "e1" and m.entity.raw_ref == "raw/e1"
    assert m.product.product_id == "B2"
