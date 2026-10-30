"""Rescue pipeline: one product in, one RescuePlan out. It never raises.

Stages, in order (names are the constants below):

  resolve   -> find the Qloo entity for the slow product        (gateway)
  insights  -> fetch entities related to it                      (gateway)
  match     -> link those entities to products the shop stocks   (matcher_service)
  generate  -> build candidate strategies                        (strategy_generator)
  check     -> run the hard constraints on every candidate       (constraints_service)
  rank      -> order the feasible candidates                     (ranking_service)
  explain   -> optional plain-language text, injected            (explain callable)

Each stage runs inside its own try/except. A stage that ran is listed in
stages_completed; a stage that raised is listed in stages_failed as
"{ExceptionType}: {message[:200]}"; a stage that was legitimately not run
(for example insights after NO_MATCH, or check after generate failed) is in
neither list. A failed stage never stops the pipeline: later stages work with
empty results, so the caller still gets a partial RescuePlan.

Division of responsibility: the gateway supplies cultural signals only, this
module wires stages together, and every number comes from the existing
deterministic services. Nothing here calculates or edits money, and nothing
calls the network. Qloo is reached only through the injected QlooGateway.

Requires pydantic (imports app.schemas.rescue).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from app.schemas.rescue import QlooStatus, RescuePlan
from app.services.constraints_service import CandidateStrategy, check_candidate
from app.services.matcher_service import (
    CandidateMatch,
    QlooRelatedEntity,
    StockItem,
    match_candidates,
)
from app.services.plan_builder import build_rescue_plan
from app.services.ranking_service import RankInput, RankingOutput, rank_strategies
from app.services.rescue_config import (
    DEFAULT_MATCH_SETTINGS,
    DEFAULT_RANKING_SETTINGS,
    DEFAULT_STRATEGY_SETTINGS,
    Constraints,
    MatchSettings,
    RankingSettings,
    StrategySettings,
)
from app.services.strategy_generator import (
    GenerationResult,
    SkippedOption,
    StrategyDraft,
    generate_strategies,
)

STAGE_RESOLVE = "resolve"
STAGE_INSIGHTS = "insights"
STAGE_MATCH = "match"
STAGE_GENERATE = "generate"
STAGE_CHECK = "check"
STAGE_RANK = "rank"
STAGE_EXPLAIN = "explain"
STAGE_BUILD = "build"  # assembling the RescuePlan itself; only ever appears in stages_failed

STAGES: Tuple[str, ...] = (
    STAGE_RESOLVE,
    STAGE_INSIGHTS,
    STAGE_MATCH,
    STAGE_GENERATE,
    STAGE_CHECK,
    STAGE_RANK,
    STAGE_EXPLAIN,
)

_BASE_LIMITATIONS: str = RescuePlan.model_fields["limitations"].default

_NOTE_UNAVAILABLE = (
    "Qloo was unavailable for this plan (service error or timeout), so no cultural "
    "evidence is used. These options rest on retailer data and commercial rules only."
)
_NOTE_NO_MATCH = (
    "Qloo found no matching entity for this product, so no cultural evidence is used. "
    "These options rest on retailer data and commercial rules only."
)
_NOTE_AMBIGUOUS = (
    "Qloo returned more than one plausible match for this product. Cultural links are "
    "treated as low-confidence until a person confirms the right entity."
)
_NOTE_AMBIGUOUS_UNCONFIRMED = (
    "Qloo returned more than one plausible match for this product and none is confirmed, "
    "so no cultural evidence is used until a person confirms the right one. These options "
    "rest on retailer data and commercial rules only."
)
_NOTE_EMPTY_INSIGHTS = (
    "Qloo matched the product but returned no related entities, so no cultural evidence "
    "is used. These options rest on retailer data and commercial rules only."
)
_NOTE_NO_ENTITY_ID = (
    "Qloo reported a match without an entity id, so it cannot be used and no cultural "
    "evidence is used. These options rest on retailer data and commercial rules only."
)
_LIMIT_NO_HISTORY = (
    "No sales history was available for this product. Missing history is not evidence "
    "that the product is unpopular, and no sales-based comparison was made."
)
_LIMIT_EXPLAIN_FAILED = (
    "The plain-language explanation step failed, so strategies are shown without it."
)


# ---------------------------------------------------------------------------
# Inputs and the gateway contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QlooResolution:
    """Result of resolving the slow product to a Qloo entity."""

    status: QlooStatus
    entity_id: Optional[str] = None
    entity_name: Optional[str] = None
    note: Optional[str] = None
    alternatives: Tuple[str, ...] = ()  # other plausible entity names (AMBIGUOUS)
    raw_ref: Optional[str] = None       # pointer to the stored raw response


@dataclass(frozen=True)
class RescueRequest:
    target: StockItem
    stock: Sequence[StockItem]
    constraints: Constraints
    has_sales_history: Optional[bool] = None  # None = unknown, False = known missing


class QlooGateway(Protocol):
    """What the pipeline needs from the Qloo layer (P1 supplies the real adapter)."""

    def resolve(self, target: StockItem) -> QlooResolution: ...

    def get_insights(self, resolution: QlooResolution) -> Sequence[QlooRelatedEntity]: ...


ExplainFn = Callable[[RescuePlan], RescuePlan]


# ---------------------------------------------------------------------------
# Stage bookkeeping
# ---------------------------------------------------------------------------

def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


class _Tracker:
    """Runs stages in try/except and records the outcome."""

    def __init__(self) -> None:
        self.completed: List[str] = []
        self.failed: Dict[str, str] = {}

    def run(self, name: str, fn: Callable[[], object], default: object = None) -> Tuple[bool, object]:
        """Return (ok, value). On failure record it and return (False, default)."""
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001 - the pipeline must never raise
            self.failed[name] = _describe(exc)
            return False, default
        self.completed.append(name)
        return True, value


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_rescue(
    request: RescueRequest,
    gateway: QlooGateway,
    *,
    explain: Optional[ExplainFn] = None,
    ranking_settings: RankingSettings = DEFAULT_RANKING_SETTINGS,
    strategy_settings: StrategySettings = DEFAULT_STRATEGY_SETTINGS,
    match_settings: MatchSettings = DEFAULT_MATCH_SETTINGS,
) -> RescuePlan:
    """Run the full pipeline and return a RescuePlan. Never raises."""
    try:
        return _run(request, gateway, explain, ranking_settings, strategy_settings, match_settings)
    except Exception as exc:  # noqa: BLE001 - last line of defence
        return _minimal_plan(request, QlooStatus.ERROR, None, [], {"pipeline": _describe(exc)})


def _run(
    request: RescueRequest,
    gateway: QlooGateway,
    explain: Optional[ExplainFn],
    ranking_settings: RankingSettings,
    strategy_settings: StrategySettings,
    match_settings: MatchSettings,
) -> RescuePlan:
    target = request.target
    constraints = request.constraints
    t = _Tracker()

    # --- resolve -----------------------------------------------------------
    status = QlooStatus.ERROR
    qloo_note: Optional[str] = _NOTE_UNAVAILABLE
    resolution: Optional[QlooResolution] = None

    def _resolve() -> QlooResolution:
        res = gateway.resolve(target)
        if not isinstance(res, QlooResolution):
            raise TypeError("gateway.resolve must return a QlooResolution")
        QlooStatus(res.status)  # raises ValueError on an unknown status
        return res

    ok, res = t.run(STAGE_RESOLVE, _resolve)
    if ok:
        resolution = res  # type: ignore[assignment]
        status = QlooStatus(resolution.status)
        if status == QlooStatus.NO_MATCH:
            qloo_note = resolution.note or _NOTE_NO_MATCH
        elif status == QlooStatus.ERROR:
            qloo_note = resolution.note or _NOTE_UNAVAILABLE
        elif status == QlooStatus.AMBIGUOUS:
            # With an entity id the links are used but treated as low-confidence; without
            # one, insights are never fetched, so say plainly that no evidence is used.
            qloo_note = _NOTE_AMBIGUOUS if resolution.entity_id else _NOTE_AMBIGUOUS_UNCONFIRMED
            if resolution.alternatives:
                qloo_note += " Other candidates: " + "; ".join(resolution.alternatives) + "."
        else:  # STRONG_MATCH
            qloo_note = resolution.note
            if not resolution.entity_id:
                status, qloo_note = QlooStatus.ERROR, _NOTE_NO_ENTITY_ID

    # --- insights ----------------------------------------------------------
    entities: Sequence[QlooRelatedEntity] = ()
    wants_insights = (
        resolution is not None
        and status in (QlooStatus.STRONG_MATCH, QlooStatus.AMBIGUOUS)
        and bool(resolution.entity_id)
    )
    if wants_insights:
        ok, got = t.run(STAGE_INSIGHTS, lambda: tuple(gateway.get_insights(resolution)), ())  # type: ignore[arg-type]
        if ok:
            entities = got  # type: ignore[assignment]
            if not entities:
                qloo_note = _NOTE_EMPTY_INSIGHTS  # status is kept as resolved
        else:
            status, qloo_note = QlooStatus.ERROR, _NOTE_UNAVAILABLE
            entities = ()

    # --- match -------------------------------------------------------------
    matches: Tuple[CandidateMatch, ...] = ()
    if entities:
        _, got = t.run(
            STAGE_MATCH,
            lambda: tuple(
                match_candidates(
                    entities, request.stock, [target.product.product_id], match_settings
                )
            ),
            (),
        )
        matches = got  # type: ignore[assignment]

    # --- generate ----------------------------------------------------------
    ok_gen, gen = t.run(
        STAGE_GENERATE,
        lambda: generate_strategies(target.product, matches, constraints, strategy_settings),
        GenerationResult(drafts=()),
    )
    drafts: Tuple[StrategyDraft, ...] = tuple(gen.drafts)  # type: ignore[attr-defined]
    skipped: Tuple[SkippedOption, ...] = tuple(gen.skipped)  # type: ignore[attr-defined]

    # --- check (needs drafts) ---------------------------------------------
    inputs: List[RankInput] = []
    ok_check = False
    if ok_gen:
        def _check() -> List[RankInput]:
            return [
                RankInput(
                    d.candidate,
                    check_candidate(d.candidate, constraints),
                    d.match_kinds,
                    d.effort,
                )
                for d in drafts
            ]

        ok_check, got = t.run(STAGE_CHECK, _check, [])
        inputs = list(got)  # type: ignore[arg-type]

    # --- rank (needs checked inputs) --------------------------------------
    ranking = RankingOutput((), ())
    if ok_check:
        _, got = t.run(
            STAGE_RANK,
            lambda: rank_strategies(inputs, status.value, constraints, ranking_settings),
            RankingOutput((), ()),
        )
        ranking = got  # type: ignore[assignment]

    # --- build the plan ----------------------------------------------------
    extra: List[str] = []
    if request.has_sales_history is False:
        extra.append(_LIMIT_NO_HISTORY)

    try:
        plan = build_rescue_plan(
            target.product,
            status,
            drafts if ranking.ranked else (),
            ranking,
            constraints,
            skipped=skipped,
            qloo_note=qloo_note,
            stages_completed=list(t.completed),
            stages_failed=dict(t.failed),
            extra_limitations=extra,
        )
    except Exception as exc:  # noqa: BLE001
        failed = dict(t.failed)
        failed[STAGE_BUILD] = _describe(exc)
        return _minimal_plan(request, status, qloo_note, list(t.completed), failed)

    # --- explain (optional) -----------------------------------------------
    if explain is not None:
        try:
            explained = explain(plan)
            if not isinstance(explained, RescuePlan):
                raise TypeError("explain must return a RescuePlan")
        except Exception as exc:  # noqa: BLE001
            failed = dict(plan.stages_failed)
            failed[STAGE_EXPLAIN] = _describe(exc)
            plan = plan.model_copy(
                update={
                    "stages_failed": failed,
                    "limitations": f"{plan.limitations} {_LIMIT_EXPLAIN_FAILED}",
                }
            )
        else:
            plan = explained.model_copy(
                update={"stages_completed": [*explained.stages_completed, STAGE_EXPLAIN]}
            )

    return plan


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def _minimal_plan(
    request: RescueRequest,
    status: QlooStatus,
    qloo_note: Optional[str],
    completed: List[str],
    failed: Dict[str, str],
) -> RescuePlan:
    """A valid plan with no strategies, used only when assembly itself failed."""
    product = getattr(getattr(request, "target", None), "product", None)
    try:
        snapshot = request.constraints.as_dict()
    except Exception:  # noqa: BLE001
        snapshot = {}
    return RescuePlan(
        product_id=str(getattr(product, "product_id", "unknown")),
        product_name=str(getattr(product, "name", "unknown")),
        qloo_status=status,
        qloo_note=qloo_note,
        strategies=[],
        rejected=[],
        constraints_snapshot=snapshot,
        stages_completed=completed,
        stages_failed=failed,
        limitations=_BASE_LIMITATIONS,
    )
