"""Log-only novelty scoring for a scout run's candidates (#49, option C).

**What this is.** Two prior rounds on #49 tried to *prevent* cross-run
repetition at the prompt: a `previously_suggested` title list injected into
synthesis (commit b4efd3f), then also briefing the pitches (PR #58, reverted).
Both were measured live on dev by the operator (issue #49, 2026-07-29 comments)
and both failed — the model restated the same concepts in different words, and
briefing more detail made the run's candidate count collapse instead. The
operator's own conclusion: *"this issue should NOT be picked up as 'make the
avoidance instruction work'"*.

The owner's 2026-09-09 decision (option C, of a four-way A/B/C/D memo) is to
build the **measurement instead of another attempt at the fix**: a per-run
novelty score a founder's candidates get judged against, so a future
A-vs-B decision has a number behind it instead of an asserted one. Explicitly
**not** built here, by that decision: any embedding-provider credential, any
persisted vector, any suppression or filtering of candidates, any re-prompting,
any threshold that changes behaviour, any change to generation. This module is
called *after* synthesis has already produced its final candidates, reads
nothing back into a prompt, and its result is logged, never persisted or acted
on.

**Why lexical similarity, not an LLM judge.** The decision memo's own framing
of option C was "one cheap OpenRouter call judges each candidate" — but that
would mean a fifth async agent role, a new run state, and a second
async round trip through the orchestration engine's fan-in for what is meant to
be a cheap, reversible measurement. A deterministic function over the text
Idea Scout already has costs nothing per run, needs no credential, and is
exactly reproducible in a test — which matters here more than usual, because
the acceptance test *is* reproducing the operator's own by-eye labelling from
the July comments (see ``tests/test_idea_scout_novelty.py``).

**Why character trigrams.** The historical failure mode named in #49 is
*thematic* restatement, not verbatim repetition — "no title ever repeated
verbatim, in any condition" was the operator's own finding across seven runs.
Word-level overlap breaks on compound-word variants of the same brand
("BedrockBudget" vs "BedrockGuard" share no whole word), and reordering
("PCI Autopilot — continuous compliance evidence for fintech teams on AWS" vs
"Compliance-Evidence Autopilot for Fintechs on AWS/GCP") defeats anything that
cares about position. Character n-grams are insensitive to both: shared
substrings survive reordering and partial-word overlap alike.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Below this character-trigram Jaccard similarity to *every* prior candidate,
#: a new candidate is labelled "novel" rather than "repeat" for logging
#: purposes. Internal to this judge only: it decides what gets printed in a log
#: line, never what a founder is shown, so it is not the "threshold that
#: changes behaviour" #49's option C explicitly excludes.
#:
#: Chosen from the separation in the operator's own four-run fixture
#: (``tests/test_idea_scout_novelty.py::test_reproduces_the_operators_own_labels``):
#: the one candidate judged genuinely new there scored 0.038 against its
#: closest prior candidate, and the closest of the three judged near-duplicate
#: scored 0.151 — nearly a 4x gap. 0.10 sits with headroom on both sides of
#: that gap rather than against either edge of it.
NOVELTY_SIMILARITY_THRESHOLD = 0.10

_NON_ALNUM = re.compile(r"[^a-z0-9 ]")
_WHITESPACE = re.compile(r"\s+")


def _trigrams(text: str) -> set[str]:
    """Character 3-grams of ``text``, lowercased with punctuation folded to
    spaces. A candidate compares as one bag of substrings rather than an
    ordered string, which is what makes this insensitive to word reordering
    and to compound-word variants of the same brand."""
    cleaned = _WHITESPACE.sub(" ", _NON_ALNUM.sub(" ", text.lower())).strip()
    if len(cleaned) < 3:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + 3] for i in range(len(cleaned) - 2)}


def _similarity(a: str, b: str) -> float:
    """Jaccard similarity of two texts' character-trigram sets, in ``[0, 1]``."""
    set_a, set_b = _trigrams(a), _trigrams(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


@dataclass(frozen=True)
class CandidateNovelty:
    """One new candidate's novelty verdict against a founder's prior candidates."""

    title: str
    #: Highest trigram similarity found against any prior candidate. ``0.0``
    #: when the founder has no prior candidates at all.
    similarity: float
    #: The prior candidate's title that produced ``similarity``, or ``None``
    #: when there was nothing to compare against.
    closest_prior_title: str | None
    is_novel: bool


@dataclass(frozen=True)
class RunNovelty:
    """A run's aggregate novelty score — the fraction of its candidates judged
    genuinely new against that founder's own prior runs."""

    candidates: tuple[CandidateNovelty, ...]

    @property
    def novelty_score(self) -> float:
        """Fraction of this run's candidates judged novel, in ``[0, 1]``.

        A run with no candidates never reaches this: ``_advance_synthesis``
        fails the run before scoring is called. A founder's *first* run
        (nothing prior to compare against) scores ``1.0`` — every candidate is
        novel relative to a founder with no history, which is the honest
        answer, not a special case.
        """
        if not self.candidates:
            return 1.0
        novel = sum(1 for c in self.candidates if c.is_novel)
        return novel / len(self.candidates)


def score_novelty(
    *,
    candidates: list[dict[str, str]],
    prior: list[dict[str, str]],
) -> RunNovelty:
    """Score this run's ``candidates`` against a founder's ``prior`` candidates.

    Both are ``[{"title": ..., "pitch": ...}, ...]``. ``prior`` must already be
    owner-scoped and must exclude this run's own candidates (the caller reads
    it before this run's candidates are saved) — this function does not
    itself enforce either, it only compares what it is given.

    Read-only and side-effect free: it does not touch generation, does not
    call out to a model, and returns a value for the caller to log.
    """
    scored: list[CandidateNovelty] = []
    for candidate in candidates:
        text = f"{candidate['title']} {candidate.get('pitch', '')}"
        best_similarity = 0.0
        best_title: str | None = None
        for prior_candidate in prior:
            prior_text = f"{prior_candidate['title']} {prior_candidate.get('pitch', '')}"
            similarity = _similarity(text, prior_text)
            if similarity > best_similarity:
                best_similarity = similarity
                best_title = prior_candidate["title"]
        scored.append(
            CandidateNovelty(
                title=candidate["title"],
                similarity=best_similarity,
                closest_prior_title=best_title,
                is_novel=best_similarity < NOVELTY_SIMILARITY_THRESHOLD,
            )
        )
    return RunNovelty(candidates=tuple(scored))
