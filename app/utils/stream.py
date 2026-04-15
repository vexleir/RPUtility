"""
Stream utilities: thought-block stripping and repetition-loop detection.
"""

from __future__ import annotations
from collections import Counter
from typing import Generator


# ── Thought-block configuration ────────────────────────────────────────────────

# Each tuple is (start_marker, end_marker) for a model's thinking-token format.
_THOUGHT_PATTERNS: list[tuple[str, str]] = [
    ("<think>",                "</think>"),        # DeepSeek-R1, Qwen3
    ("<|channel>thought",      "<channel|>"),      # Gemma 3 thinking
    ("<start_of_turn>thought", "<end_of_turn>"),   # Gemma chat thinking variant
]

_MAX_START_LEN = max(len(s) for s, _ in _THOUGHT_PATTERNS)


# ── Public API ─────────────────────────────────────────────────────────────────

def strip_thought_blocks(
    stream_gen: Generator[str, None, None],
) -> Generator[str, None, None]:
    """
    Wrap a token generator and drop all content inside thinking blocks.

    Each start marker is paired with its own end marker (not any end marker),
    so mixed-format responses are handled correctly. Multi-chunk markers
    (split across a chunk boundary) are handled via a small lookahead buffer.
    Multiple thinking blocks in one response are all stripped.
    """
    buf = ""
    in_block = False
    end_marker = ""

    for chunk in stream_gen:
        buf += chunk

        while buf:
            if in_block:
                idx = buf.find(end_marker)
                if idx != -1:
                    # Discard everything up to and including the end marker.
                    buf = buf[idx + len(end_marker):]
                    in_block = False
                else:
                    # End marker not yet fully received — keep a tail so the
                    # next chunk can complete it.
                    keep = len(end_marker) - 1
                    buf = buf[-keep:] if keep > 0 else ""
                    break
            else:
                # Find the earliest start marker in the buffer.
                earliest_idx: int | None = None
                matched_start = ""
                matched_end = ""
                for start, end in _THOUGHT_PATTERNS:
                    idx = buf.find(start)
                    if idx != -1 and (earliest_idx is None or idx < earliest_idx):
                        earliest_idx = idx
                        matched_start = start
                        matched_end = end

                if earliest_idx is not None:
                    # Yield content before the start marker, then enter block.
                    if earliest_idx > 0:
                        yield buf[:earliest_idx]
                    in_block = True
                    end_marker = matched_end
                    buf = buf[earliest_idx + len(matched_start):]
                else:
                    # No start marker — yield safely, keeping a partial-marker
                    # tail in case one spans the next chunk boundary.
                    safe = len(buf) - _MAX_START_LEN
                    if safe > 0:
                        yield buf[:safe]
                        buf = buf[safe:]
                    break

    # Flush anything remaining after the stream ends.
    if not in_block and buf:
        yield buf


def strip_thoughts_from_text(text: str) -> str:
    """
    Strip all thinking blocks from a complete (non-streaming) string.
    Each start marker is paired with its own matching end marker.
    Unclosed blocks are truncated at the start marker.
    """
    changed = True
    while changed:
        changed = False
        earliest_idx: int | None = None
        matched_start = ""
        matched_end = ""
        for start, end in _THOUGHT_PATTERNS:
            idx = text.find(start)
            if idx != -1 and (earliest_idx is None or idx < earliest_idx):
                earliest_idx = idx
                matched_start = start
                matched_end = end

        if earliest_idx is None:
            break

        end_idx = text.find(matched_end, earliest_idx + len(matched_start))
        if end_idx != -1:
            text = text[:earliest_idx] + text[end_idx + len(matched_end):]
            changed = True
        else:
            # Unclosed block — strip everything from the start marker onward.
            text = text[:earliest_idx]
            break

    return text.strip()


def break_loops(
    stream_gen: Generator[str, None, None],
    window_words: int = 300,
    ngram_size: int = 4,
    max_repeats: int = 3,
) -> Generator[str, None, None]:
    """
    Terminate a stream early when a word n-gram repetition loop is detected.

    Uses word n-grams (not raw character strings) so near-repetitions are
    caught even when small words vary:
        "his hips finding their rhythm"
        "his hips finding their perfect rhythm"   ← different last word
        "his hips finding their insistent rhythm" ← still caught by 4-gram

    Punctuation is stripped before comparison so "rhythm," and "rhythm." match.
    The most frequent n-gram in the window is checked (not just the last one),
    so loops are detected regardless of what the current tail words are.

    Parameters
    ----------
    window_words : Number of recent words to inspect for loops.
    ngram_size   : Word n-gram length to use for pattern detection.
    max_repeats  : Stop when any n-gram has appeared this many times in the window.
    """
    history = ""

    for chunk in stream_gen:
        history += chunk
        yield chunk

        if len(history) < 100:
            continue

        # Normalise the tail into word tokens.
        raw_words = history.split()
        words = [
            w.lower().rstrip(".,!?;:'\"")
            for w in raw_words[-window_words:]
        ]

        if len(words) < ngram_size * max_repeats:
            continue

        # Count every n-gram in the window; halt if the most common one repeats.
        counts = Counter(
            tuple(words[i : i + ngram_size])
            for i in range(len(words) - ngram_size + 1)
        )
        if counts.most_common(1)[0][1] >= max_repeats:
            return  # Repetition loop detected — halt the stream.
