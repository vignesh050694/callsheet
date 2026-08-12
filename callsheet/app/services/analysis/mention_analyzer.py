"""The analysis port a reprocess runs through (E03-S04).

This story owns *when* analysis happens and *how its output is versioned and stored*. It
does not own what analysis says — language identification, account typing, sentiment and
theme extraction are E04, each with its own story and its own accuracy gate.

Keeping the two apart is the whole point of the epic. Analysis is the budget risk
($90-$900 per title, concept note §7), and it is the thing most likely to be replaced by a
better model mid-pilot. A pipeline that could only produce derived fields at collection
time would force a re-collection every time the model improved, which is exactly the cost
this architecture exists to avoid.

`pipeline_version` is the analyzer's identity, not a timestamp. Two analyses of the same
mention under different versions coexist, so a reprocess is additive: the old results stay
readable until the new run finishes, and a regression can be compared against rather than
merely regretted.
"""

import abc
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

import structlog

from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform

_logger = structlog.get_logger(__name__)

ANALYSIS_UNAVAILABLE_MESSAGE = (
    "No analysis pipeline is configured on this deployment, so there is nothing to "
    "recompute. Collected mentions and their raw payloads are unaffected."
)


@dataclass(frozen=True, slots=True)
class AnalyzableMention:
    """What an analyzer is given: the post, and nothing already concluded about it.

    `platform_reported_language` is passed deliberately, and named for its provenance so
    an analyzer cannot mistake it for an answer. E04-S01 requires detection to read the
    text and ignore this tag, keeping it only as a diagnostic — measuring how often the
    two disagree is a quality signal worth having, but it is never an input to the
    decision.
    """

    mention_id: str
    platform: Platform
    text: str
    posted_at: datetime
    author_handle: str
    author_follower_count: int | None = None
    hashtags: list[str] = field(default_factory=list)
    platform_reported_language: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisVerdict:
    """One analyzer's conclusions about one mention.

    Named a verdict rather than an analysis to keep it distinct from the `MentionAnalysis`
    row it eventually becomes: this is what a pipeline *decided*, before anything has been
    stored or versioned.

    Every field is optional because the pipeline is assembled from independent steps that
    ship in separate stories. A version that only detects language leaves sentiment null,
    and null must read as "this version did not judge that" rather than as a neutral
    score — a zero here would be a number nothing stands behind, on a screen where numbers
    are the product.
    """

    mention_id: str
    detected_language: str | None = None
    language_confidence: float | None = None
    is_code_mixed: bool | None = None
    account_type: str | None = None
    account_type_confidence: float | None = None
    sentiment_label: str | None = None
    sentiment_confidence: float | None = None
    themes: list[str] = field(default_factory=list)


class MentionAnalyzer(abc.ABC):
    """One version of the analysis pipeline."""

    @property
    @abc.abstractmethod
    def pipeline_version(self) -> str:
        """Identifies this pipeline's output. Stored on every row it produces."""

    @abc.abstractmethod
    async def analyze(self, mentions: Sequence[AnalyzableMention]) -> list[AnalysisVerdict]:
        """Judges a batch. Returns at most one analysis per mention, in any order."""


class UnconfiguredMentionAnalyzer(MentionAnalyzer):
    """The default binding until E04 supplies a pipeline.

    Refuses rather than returning empty analyses, on the same reasoning as the unconfigured
    collection source: an empty result is indistinguishable from a real one that found
    nothing, and a dashboard cannot tell "not analysed" from "analysed as neutral".
    """

    @property
    def pipeline_version(self) -> str:
        return "unconfigured"

    async def analyze(self, mentions: Sequence[AnalyzableMention]) -> list[AnalysisVerdict]:
        _logger.warning("analysis.analyzer.unconfigured", mention_count=len(mentions))
        raise ServiceUnavailableError(ANALYSIS_UNAVAILABLE_MESSAGE)
