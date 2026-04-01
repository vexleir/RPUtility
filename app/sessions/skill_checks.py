"""
Skill Check store + dice-roll logic.

Supports any NdM dice notation (e.g. "d20", "2d6", "d100").
Default is d20, which uses natural-20/natural-1 critical rules.
For non-d20 checks, criticals are determined by margin of success/failure.
"""

from __future__ import annotations

import random
import re
from datetime import datetime

from app.core.database import get_connection
from app.core.models import CharacterStat, CheckOutcome, SkillCheckResult


# ── Dice rolling ──────────────────────────────────────────────────────────────

def parse_dice(notation: str) -> tuple[int, int]:
    """
    Parse NdM notation. Returns (count, sides).
    Examples: "d20" → (1, 20), "2d6" → (2, 6), "d100" → (1, 100).
    """
    notation = notation.strip().lower()
    m = re.match(r"^(\d*)d(\d+)$", notation)
    if not m:
        raise ValueError(f"Invalid dice notation: {notation!r}. Use NdM, e.g. 'd20' or '2d6'.")
    count = int(m.group(1)) if m.group(1) else 1
    sides = int(m.group(2))
    if count < 1 or sides < 2:
        raise ValueError(f"Dice count must be ≥1 and sides ≥2, got {count}d{sides}.")
    return count, sides


def roll_dice(notation: str = "d20") -> tuple[int, list[int]]:
    """
    Roll dice. Returns (total, individual_rolls).
    """
    count, sides = parse_dice(notation)
    rolls = [random.randint(1, sides) for _ in range(count)]
    return sum(rolls), rolls


def determine_outcome(
    roll: int,
    total: int,
    difficulty: int,
    dice: str = "d20",
) -> CheckOutcome:
    """
    Determine check outcome.
    d20: natural 20 = critical success, natural 1 = critical failure.
    Others: margin of ±5+ determines criticals.
    """
    _, sides = parse_dice(dice)
    count, _ = parse_dice(dice)

    if count == 1 and sides == 20:
        # Classic d20 critical rules
        if roll == 20:
            return CheckOutcome.CRITICAL_SUCCESS
        if roll == 1:
            return CheckOutcome.CRITICAL_FAILURE
    else:
        # Margin-based criticals for non-d20 systems
        margin = total - difficulty
        if margin >= 10:
            return CheckOutcome.CRITICAL_SUCCESS
        if margin <= -10:
            return CheckOutcome.CRITICAL_FAILURE

    return CheckOutcome.SUCCESS if total >= difficulty else CheckOutcome.FAILURE


# ── Store ─────────────────────────────────────────────────────────────────────

class SkillCheckStore:
    def __init__(self, db_path: str) -> None:
        self._db = db_path

    def save(self, result: SkillCheckResult) -> None:
        with get_connection(self._db) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO skill_checks
                    (id, session_id, stat_name, roll, modifier, total,
                     difficulty, outcome, narrative_context, turn_number, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.id, result.session_id, result.stat_name,
                result.roll, result.modifier, result.total,
                result.difficulty, result.outcome.value,
                result.narrative_context, result.turn_number,
                result.created_at.isoformat(),
            ))

    def delete_session(self, session_id: str) -> None:
        with get_connection(self._db) as conn:
            conn.execute(
                "DELETE FROM skill_checks WHERE session_id=?", (session_id,)
            )

    def get_all(self, session_id: str) -> list[SkillCheckResult]:
        """Most recent first."""
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM skill_checks WHERE session_id=? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        return [_row_to_check(r) for r in rows]

    def get_recent(self, session_id: str, n: int = 10) -> list[SkillCheckResult]:
        with get_connection(self._db) as conn:
            rows = conn.execute(
                "SELECT * FROM skill_checks WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, n),
            ).fetchall()
        return [_row_to_check(r) for r in rows]


# ── Engine-level roll helper ──────────────────────────────────────────────────

def perform_check(
    session_id: str,
    stat: CharacterStat | None,
    stat_name: str,
    difficulty: int,
    dice: str = "d20",
    narrative_context: str = "",
    turn_number: int = 0,
) -> SkillCheckResult:
    """
    Roll the dice, apply modifier from stat (if provided), determine outcome.
    Returns an unsaved SkillCheckResult — caller must persist it.
    """
    raw_roll, _ = roll_dice(dice)
    mod = stat.effective_modifier if stat else 0
    total = raw_roll + mod
    outcome = determine_outcome(raw_roll, total, difficulty, dice)

    return SkillCheckResult(
        session_id=session_id,
        stat_name=stat_name,
        roll=raw_roll,
        modifier=mod,
        total=total,
        difficulty=difficulty,
        outcome=outcome,
        narrative_context=narrative_context,
        turn_number=turn_number,
    )


def _row_to_check(row) -> SkillCheckResult:
    return SkillCheckResult(
        id=row["id"],
        session_id=row["session_id"],
        stat_name=row["stat_name"],
        roll=row["roll"],
        modifier=row["modifier"],
        total=row["total"],
        difficulty=row["difficulty"],
        outcome=CheckOutcome(row["outcome"]),
        narrative_context=row["narrative_context"] or "",
        turn_number=row["turn_number"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
