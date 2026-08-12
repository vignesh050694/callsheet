"""May this organization spend on a poll right now (E03-S01, owned by E09).

The story's first scenario is conditioned on "my organization is within its spend
controls". Cost governance itself is E09 — budgets, tiers, projections, the alerts when a
title is on course to overrun. What belongs *here* is the seam: a scheduler that has no
way to ask the question can never be made to respect the answer, and retrofitting a check
into a worker loop is how a governance rule becomes a code review convention.

So the check exists from the first cycle and defaults to permitting. That default announces
itself in the log of every cycle it permits, because "nothing stopped it" and "a budget was
checked and had room" must not look the same to somebody reconciling against an invoice.
"""

import abc
import uuid
from dataclasses import dataclass

import structlog

_logger = structlog.get_logger(__name__)

NO_BUDGET_CONFIGURED_REASON = "no spend policy is configured on this deployment"


@dataclass(frozen=True, slots=True)
class SpendDecision:
    """Whether a cycle may run, and the reason either way.

    The reason is required in both directions. A refusal that cannot say why produces a
    title that quietly stops collecting, which is the failure this layer works hardest to
    make impossible to mistake for silence.
    """

    is_allowed: bool
    reason: str


class SpendPolicy(abc.ABC):
    @abc.abstractmethod
    async def decide(self, organization_id: uuid.UUID) -> SpendDecision:
        """Whether this organization may pay for one more collection cycle."""


class UnrestrictedSpendPolicy(SpendPolicy):
    """The default binding until E09 lands: always allows, and says that it is why.

    Deliberately not silent, and deliberately at `info` rather than `debug`. The default
    log level is `info`, so a `debug` line here would be invisible on every deployment that
    has not opted into verbose logging — which is exactly the deployment this warning is
    for. A permissive default nobody can see in the log is indistinguishable from a
    governed one with generous limits, which is the confusion this class exists to prevent.
    """

    async def decide(self, organization_id: uuid.UUID) -> SpendDecision:
        _logger.info(
            "collection.spend.unrestricted",
            organization_id=str(organization_id),
            reason=NO_BUDGET_CONFIGURED_REASON,
        )
        return SpendDecision(is_allowed=True, reason=NO_BUDGET_CONFIGURED_REASON)
