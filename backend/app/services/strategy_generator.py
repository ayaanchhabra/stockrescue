"""Strategy generator: turns a slow product plus its matched partners into
candidate strategies.

It proposes, at most, one of each distinct type:

  bundle      the slow product + ONE stocked partner linked through Qloo.
              Partners are tried strongest link first. The generator stops at
              the first bundle that passes the hard constraints, but keeps the
              earlier ones it tried so their rejection reasons stay visible.
  reposition  a new display for the slow product at its normal price. If stocked
              titles were linked through Qloo, the display is themed around them.
  promotion   a controlled discount sized with max_allowed_discount_pct(), so it
              respects both the discount cap and the margin floor.

This module only PROPOSES. The constraint engine (constraints_service) still
checks every candidate and the ranking service orders them; the generator
calls the checker only to decide which bundle partner to stop at.

All money comes from economics_service / constraints_service. Campaign costs and
the test length are placeholder assumptions from StrategySettings and are
labelled as such in the output. Nothing here predicts sales or uplift.

Pure Python: no pydantic, no network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from . import economics_service as eco
from .constraints_service import (
    BUNDLE,
    PROMOTION,
    REPOSITION,
    CandidateStrategy,
    ProductRef,
    check_candidate,
    effective_max_discount,
    effective_min_margin,
    max_allowed_discount_pct,
)
from .economics_service import EconomicsError
from .matcher_service import (
    FUZZY,
    THEME_ONLY,
    CandidateMatch,
    match_sort_key,
)
from .rescue_config import (
    DEFAULT_STRATEGY_SETTINGS,
    Constraints,
    StrategySettings,
)

# Operational effort values (match RankingSettings.effort_scores keys)
LOW = "low"
MEDIUM = "medium"


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyDraft:
    """A candidate plus the descriptive fields the plan builder needs."""

    candidate: CandidateStrategy
    effort: str                              # "low" | "medium" | "high"
    match_kinds: Tuple[str, ...]             # one per Qloo link relied on (for ranking)
    links: Tuple[CandidateMatch, ...]        # the Qloo links behind this strategy (evidence)
    summary: str
    test_plan: str
    assumptions: Tuple[str, ...] = ()
    risks: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SkippedOption:
    """An option the generator could not even build, with the reasons why.

    The plan builder shows these next to the constraint-rejected options.
    """

    strategy_type: str
    name: str
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class GenerationResult:
    drafts: Tuple[StrategyDraft, ...]
    skipped: Tuple[SkippedOption, ...] = ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_problem(product: ProductRef) -> Optional[str]:
    """Same validity rule the constraint engine uses, so we never price bad data."""
    if (
        product.selling_price is None or product.selling_price <= 0
        or product.unit_cost is None or product.unit_cost < 0
        or product.quantity is None or product.quantity < 0
    ):
        return f"Invalid price, cost or stock data for '{product.name}'."
    return None


def _whole_rupee_up(price: float) -> float:
    """Round up to a whole rupee. Rounding up can only raise margin, never break it."""
    return float(math.ceil(round(price, 6)))


def _group_by_product(
    matches: Sequence[CandidateMatch], exclude_ids: Sequence[str]
) -> List[List[CandidateMatch]]:
    """Links grouped per product (strongest first), best-linked products first."""
    groups: Dict[str, List[CandidateMatch]] = {}
    for m in sorted(matches, key=match_sort_key):
        if m.product.product_id in exclude_ids:
            continue
        groups.setdefault(m.product.product_id, []).append(m)
    ordered = list(groups.values())
    ordered.sort(key=lambda g: (match_sort_key(g[0])[:2], -g[0].product.quantity, g[0].product.name.casefold()))
    return ordered


def _link_risk(kind: str, partner_name: str) -> Optional[str]:
    if kind == FUZZY:
        return (
            f"The link to '{partner_name}' is a fuzzy name or creator match; "
            "a person should confirm it is relevant."
        )
    if kind == THEME_ONLY:
        return (
            f"'{partner_name}' is connected only through a shared theme, "
            "which is weaker evidence than a title or creator link."
        )
    return None


def _money(x: float) -> str:
    return f"Rs {x:,.2f}".replace(".00", "")


def _test_plan(settings: StrategySettings, what: str, target: ProductRef) -> str:
    d = settings.test_days
    return (
        f"{what} for {d} days. Record units sold, the actual price paid and any direct "
        f"campaign cost. Compare the daily sales rate of '{target.name}' with its previous "
        f"{d} days. A before/after change is not proof the change caused it, so also note "
        "season, placement and footfall."
    )


def _placeholder_cost_assumption(cost: float) -> str:
    return (
        f"Campaign cost of {_money(cost)} is a placeholder from the settings, "
        "not a measured figure; replace it with the shop's real cost."
    )


# ---------------------------------------------------------------------------
# Individual strategies
# ---------------------------------------------------------------------------

def _bundle_price(
    target: ProductRef, partner: ProductRef, constraints: Constraints, s: StrategySettings
) -> float:
    """Price for ONE bundle: a modest saving vs the separate prices, never below the
    margin floor when the floor allows any saving at all."""
    products = (target, partner)
    separate_total = eco.discounted_price(sum(p.selling_price for p in products), 0)
    cost = eco.bundle_unit_cost([p.unit_cost for p in products])

    discount = min(s.bundle_discount_pct, effective_max_discount(products, constraints))
    price = eco.discounted_price(separate_total, discount)

    floor = eco.min_price_for_margin(cost, effective_min_margin(products, constraints))
    if floor >= separate_total:
        # Even full price may not meet the margin floor. Offer no saving and let the
        # constraint engine report the real reason.
        return separate_total
    price = max(price, floor)
    return min(_whole_rupee_up(price), separate_total)


def _make_bundle(
    target: ProductRef,
    links: Sequence[CandidateMatch],
    constraints: Constraints,
    s: StrategySettings,
) -> StrategyDraft:
    partner = links[0].product
    price = _bundle_price(target, partner, constraints, s)
    separate = [target.selling_price, partner.selling_price]
    saving = eco.bundle_discount_vs_separate_pct(price, separate)
    kinds = tuple(m.match_kind for m in links)

    entity_names = ", ".join(f"'{m.entity.name}'" for m in links[:2])
    assumptions = [
        f"Customers interested in {entity_names} may also be interested in this pairing. "
        "This is a hypothesis from a Qloo link, not proof that the bundle will sell.",
        f"Bundle price is set about {saving:.0f}% below buying the two items separately.",
        _placeholder_cost_assumption(s.bundle_campaign_cost),
    ]
    risks = [
        f"Each bundle uses one unit of '{partner.name}' ({partner.quantity} in stock).",
    ]
    link_risk = _link_risk(links[0].match_kind, partner.name)
    if link_risk:
        risks.append(link_risk)
    if saving < 1:
        risks.append(
            "The bundle gives no saving over buying the items separately, "
            "so it may not attract customers."
        )

    name = f"Bundle: {target.name} + {partner.name}"
    candidate = CandidateStrategy(
        BUNDLE, name, (target, partner), price,
        s.bundle_campaign_cost, s.test_units,
    )
    return StrategyDraft(
        candidate=candidate,
        effort=MEDIUM,
        match_kinds=kinds,
        links=tuple(links),
        summary=(
            f"Sell '{target.name}' together with '{partner.name}' for {_money(price)} "
            f"(separately {_money(sum(separate))})."
        ),
        test_plan=_test_plan(s, f"Offer the bundle at {_money(price)}", target),
        assumptions=tuple(assumptions),
        risks=tuple(risks),
    )


def _make_reposition(
    target: ProductRef,
    groups: Sequence[Sequence[CandidateMatch]],
    s: StrategySettings,
    constraints: Constraints,
) -> StrategyDraft:
    # Only titles on the shelf can sit in a display (the matcher keeps zero-stock
    # items so a bundle with one is rejected visibly, but a display needs stock).
    # Restricted products are never named in a display either: the constraint
    # engine only sees the target here, so the rule has to be applied now.
    restricted = constraints.restricted_product_ids
    eligible = [g for g in groups if g[0].product.product_id not in restricted]
    shown = [g for g in eligible if g[0].product.quantity > 0][: s.max_display_titles]
    linked_but_unusable = bool(groups) and not shown
    links = tuple(g[0] for g in shown)  # best link of each displayed title
    kinds = tuple(m.match_kind for m in links)

    if links:
        titles = ", ".join(f"'{m.product.name}'" for m in links)
        name = f"Themed display: {target.name}"
        summary = (
            f"Give '{target.name}' a themed display alongside related stocked titles: {titles}. "
            f"Price stays at {_money(target.selling_price)}."
        )
        assumptions = [
            "Customers browsing the related titles may notice this book. "
            "This is a hypothesis from Qloo links, not proof it will sell.",
            "The display changes visibility only; the price is unchanged.",
        ]
        risks = [r for r in (_link_risk(m.match_kind, m.product.name) for m in links) if r]
        what = "Run the themed display"
    else:
        name = f"Face-out display: {target.name}"
        why = (
            "Related titles were linked, but none can be shown (out of stock or restricted)"
            if linked_but_unusable
            else "No cultural link was available"
        )
        summary = (
            f"Move '{target.name}' to a prominent face-out display at its normal price "
            f"of {_money(target.selling_price)}. {why}, so there is no themed angle."
        )
        assumptions = [
            "Better placement may increase visibility. This is an untested hypothesis.",
            "The display changes visibility only; the price is unchanged.",
        ]
        risks = ["There is no cultural evidence behind this option; it rests on placement alone."]
        what = "Run the display"

    assumptions.append(_placeholder_cost_assumption(s.reposition_campaign_cost))
    candidate = CandidateStrategy(
        REPOSITION, name, (target,), target.selling_price,
        s.reposition_campaign_cost, s.test_units,
    )
    return StrategyDraft(
        candidate=candidate,
        effort=LOW,
        match_kinds=kinds,
        links=links,
        summary=summary,
        test_plan=_test_plan(s, what, target),
        assumptions=tuple(assumptions),
        risks=tuple(risks),
    )


def _make_promotion(
    target: ProductRef, constraints: Constraints, s: StrategySettings
) -> Tuple[Optional[StrategyDraft], Optional[SkippedOption]]:
    try:
        allowed = max_allowed_discount_pct(target, constraints)
    except EconomicsError as exc:
        return None, SkippedOption(
            PROMOTION, f"Controlled promotion: {target.name}",
            (f"Could not size a discount: {exc}",),
        )

    discount = min(s.promo_discount_pct, allowed)
    if discount < s.min_promo_discount_pct:
        return None, SkippedOption(
            PROMOTION, f"Controlled promotion: {target.name}",
            (
                f"The largest discount your rules allow is {allowed:.2f}% (discount cap and "
                f"margin floor combined), below the {s.min_promo_discount_pct:.0f}% minimum "
                "worth testing.",
            ),
        )

    price = eco.discounted_price(target.selling_price, discount)
    rounded = _whole_rupee_up(price)
    if rounded < target.selling_price:
        price = rounded
    actual = eco.discount_pct_between(target.selling_price, price)

    name = f"Controlled promotion: {actual:.0f}% off {target.name}"
    candidate = CandidateStrategy(
        PROMOTION, name, (target,), price,
        s.promotion_campaign_cost, s.test_units,
    )
    return StrategyDraft(
        candidate=candidate,
        effort=LOW,
        match_kinds=(),
        links=(),
        summary=(
            f"Sell '{target.name}' at {_money(price)} instead of {_money(target.selling_price)} "
            f"(about {actual:.0f}% off). The largest discount your rules allow is {allowed:.2f}%."
        ),
        test_plan=_test_plan(s, f"Offer the discounted price of {_money(price)}", target),
        assumptions=(
            "A lower price may increase sales. This is an untested hypothesis, and a "
            "discount lowers profit on every unit sold.",
            _placeholder_cost_assumption(s.promotion_campaign_cost),
        ),
        risks=(
            "Discounting reduces gross profit per unit and can teach customers to wait "
            "for markdowns. It is ranked after non-discount options for that reason.",
        ),
    ), None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_strategies(
    target: ProductRef,
    matches: Sequence[CandidateMatch],
    constraints: Constraints,
    settings: StrategySettings = DEFAULT_STRATEGY_SETTINGS,
) -> GenerationResult:
    """Build candidate strategies for one slow product.

    `matches` are the Qloo-to-stock links from matcher_service (empty when Qloo
    gave nothing usable). The target itself is never used as a partner.
    """
    problem = _data_problem(target)
    if problem:
        return GenerationResult(
            (),
            tuple(
                SkippedOption(t, f"{label}: {target.name}", (problem,))
                for t, label in (
                    (BUNDLE, "Bundle"),
                    (REPOSITION, "Display"),
                    (PROMOTION, "Controlled promotion"),
                )
            ),
        )

    drafts: List[StrategyDraft] = []
    skipped: List[SkippedOption] = []

    # --- bundle ------------------------------------------------------------
    groups = _group_by_product(matches, [target.product_id])
    if not groups:
        skipped.append(SkippedOption(
            BUNDLE, f"Bundle: {target.name}",
            ("No stocked product could be linked to a cultural signal, so there is "
             "no partner to bundle with.",),
        ))
    else:
        attempts = 0
        blocked_shown = 0
        for links in groups:
            if attempts >= settings.max_bundle_attempts:
                break
            partner = links[0].product
            problem = _data_problem(partner)
            if problem:
                skipped.append(SkippedOption(
                    BUNDLE, f"Bundle: {target.name} + {partner.name}", (problem,)))
                continue
            # A restricted or out-of-stock partner can never pass. Show a few so the
            # rejection stays visible, but do not let them use up the attempts that
            # are meant for partners that could actually work.
            blocked = (
                partner.product_id in constraints.restricted_product_ids
                or partner.quantity < settings.test_units
            )
            if blocked:
                if blocked_shown >= settings.max_bundle_attempts:
                    continue
                blocked_shown += 1
            try:
                draft = _make_bundle(target, links, constraints, settings)
            except EconomicsError as exc:
                skipped.append(SkippedOption(
                    BUNDLE, f"Bundle: {target.name} + {partner.name}",
                    (f"Could not price the bundle: {exc}",)))
                continue
            drafts.append(draft)
            if not blocked:
                attempts += 1
            if check_candidate(draft.candidate, constraints).passed:
                break  # one feasible bundle is enough; later partners are not needed

    # --- reposition --------------------------------------------------------
    drafts.append(_make_reposition(target, groups, settings, constraints))

    # --- promotion ---------------------------------------------------------
    promo, promo_skipped = _make_promotion(target, constraints, settings)
    if promo is not None:
        drafts.append(promo)
    if promo_skipped is not None:
        skipped.append(promo_skipped)

    return GenerationResult(tuple(drafts), tuple(skipped))
