"""
Context budget manager.

Prevents context-window overflow by trimming the oldest conversation turns
before the message list is sent to the model.

Strategy
--------
- The system message and the final user turn are NEVER trimmed.
- Oldest assistant/user history pairs are dropped first (FIFO).
- A safety margin is applied so we always leave headroom for the model reply.
- Token estimation uses the fast heuristic: len(text) // 4 ≈ token count.
  This avoids a tokeniser dependency and is accurate enough for budgeting.

Usage
-----
    from app.prompting.budget import apply_context_budget

    messages = build_messages(...)
    messages = apply_context_budget(messages, context_window=config.context_window)
"""

from __future__ import annotations

import logging

log = logging.getLogger("rp_utility")

# Fraction of the context window reserved for the model's reply.
# At 16 384 ctx this reserves ~2 048 tokens for the response.
_REPLY_HEADROOM_FRACTION = 0.125

# Absolute minimum headroom tokens regardless of context_window.
_MIN_HEADROOM_TOKENS = 512


def _estimate_tokens(text: str) -> int:
    """Fast, dependency-free token count estimate (chars ÷ 4)."""
    return max(1, len(text) // 4)


def _messages_tokens(messages: list[dict]) -> int:
    return sum(_estimate_tokens(m.get("content", "")) for m in messages)


def apply_context_budget(
    messages: list[dict],
    context_window: int,
    *,
    headroom_fraction: float = _REPLY_HEADROOM_FRACTION,
    min_headroom: int = _MIN_HEADROOM_TOKENS,
) -> list[dict]:
    """
    Trim the oldest conversation-history turns from *messages* so the total
    estimated token count stays within the available budget.

    Parameters
    ----------
    messages:
        Full message list as returned by build_messages() / build_scene_messages().
        Expected layout: [system, ...history..., user].
    context_window:
        The model's maximum context length in tokens.
    headroom_fraction:
        Fraction of context_window to reserve for the model's reply.
    min_headroom:
        Minimum tokens always reserved for the model's reply.

    Returns
    -------
    The (possibly trimmed) message list.  Always contains at minimum the system
    message and the final user turn.
    """
    if context_window <= 0:
        return messages

    headroom = max(min_headroom, int(context_window * headroom_fraction))
    budget = context_window - headroom

    total = _messages_tokens(messages)
    if total <= budget:
        return messages  # nothing to do

    # Separate structural messages from trimmable history.
    # Layout: messages[0] = system, messages[-1] = final user turn,
    # messages[1:-1] = conversation history.
    if len(messages) <= 2:
        # Only system + user — nothing we can trim.
        return messages

    system_msg = messages[0]
    final_user = messages[-1]
    history = list(messages[1:-1])  # mutable copy

    system_tokens = _estimate_tokens(system_msg.get("content", ""))
    final_tokens = _estimate_tokens(final_user.get("content", ""))
    fixed_tokens = system_tokens + final_tokens

    if fixed_tokens >= budget:
        # System prompt alone exceeds budget — can't help, return as-is and
        # let the model/provider handle the overflow (it will truncate).
        log.warning(
            "Context budget: system prompt (%d tok) + final user turn (%d tok) "
            "already exceeds budget (%d tok). Cannot trim history further.",
            system_tokens,
            final_tokens,
            budget,
        )
        return messages

    history_budget = budget - fixed_tokens
    original_len = len(history)

    # Drop pairs from the front (oldest first) until we fit.
    # We work with individual turns so odd-length history is handled safely.
    while history:
        history_tokens = sum(_estimate_tokens(m.get("content", "")) for m in history)
        if history_tokens <= history_budget:
            break
        history.pop(0)  # drop oldest turn

    dropped = original_len - len(history)
    if dropped:
        log.debug(
            "Context budget: dropped %d old turn(s) to fit within %d-token window "
            "(budget=%d, headroom=%d).",
            dropped,
            context_window,
            budget,
            headroom,
        )

    return [system_msg, *history, final_user]
