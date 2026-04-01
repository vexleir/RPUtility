"""
Example session walkthrough — demonstrates memory creation and recall.

This script:
1. Loads the example character card and lorebook
2. Creates a new session
3. Simulates a multi-turn conversation with memory events injected
4. Shows how memory persists and is recalled in later turns
5. Demonstrates the developer inspection tools

Run with:
    python example_session.py

Requires a running Ollama instance with the configured model.
To use LM Studio instead, set RP_PROVIDER=lmstudio before running.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import config
from app.core.engine import RoleplayEngine
from app.core.models import MemoryEntry, MemoryType, ImportanceLevel
from app.devtools.inspector import (
    print_memories,
    print_scene,
    print_relationships,
    print_prompt,
)
from datetime import datetime


def separator(title: str = "") -> None:
    print(f"\n{'=' * 60}")
    if title:
        print(f"  {title}")
        print(f"{'=' * 60}")


def main():
    separator("RP Utility — Example Session")
    print(f"Provider: {config.provider} | Model: {config.active_model()}")

    engine = RoleplayEngine(config)

    # ── Check provider ────────────────────────────────────────────────────
    if not engine.provider.is_available():
        print(
            "\nERROR: Model provider is not reachable.\n"
            "Make sure Ollama is running: ollama serve\n"
            "Or switch to LM Studio: RP_PROVIDER=lmstudio python example_session.py"
        )
        sys.exit(1)

    # ── Create session ────────────────────────────────────────────────────
    separator("Creating Session")
    session = engine.new_session(
        name="The Crosshaven Affair",
        character_name="Lyra Ashveil",
        lorebook_name="Crosshaven and the Ashfen",
        initial_location="Tallow & Ink tavern, Crosshaven",
        initial_characters=["Lyra Ashveil"],
    )
    print(f"Session ID: {session.id}")
    print(f"Character:  {session.character_name}")
    print(f"Lorebook:   {session.lorebook_name}")

    # ── First message ─────────────────────────────────────────────────────
    separator("First Message (Character Greeting)")
    card = engine.get_card("Lyra Ashveil")
    if card and card.first_message:
        print(f"\nLyra: {card.first_message}")

    # ── Turn 1: Introduction ──────────────────────────────────────────────
    separator("Turn 1")
    user1 = "I need help finding a way into the Old Archive vaults. I was told you know how."
    print(f"You: {user1}\n")
    response1 = engine.chat(session.id, user1)
    print(f"Lyra: {response1}")

    # ── Inject a memory manually (simulating what memory extraction would do) ──
    # In real use, this happens automatically after each turn.
    engine.memory_store.save(MemoryEntry(
        session_id=session.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        type=MemoryType.EVENT,
        title="Player asked about the Old Archive",
        content="The player character approached Lyra at the Tallow & Ink and asked about accessing the Old Archive vaults in Crosshaven.",
        entities=["Lyra Ashveil", "Player", "Old Archive"],
        location="Tallow & Ink tavern, Crosshaven",
        tags=["archive", "crosshaven", "first meeting"],
        importance=ImportanceLevel.HIGH,
    ))

    # ── Turn 2: Follow-up ─────────────────────────────────────────────────
    separator("Turn 2")
    user2 = "What's down there? What are they hiding?"
    print(f"You: {user2}\n")
    response2 = engine.chat(session.id, user2)
    print(f"Lyra: {response2}")

    # ── Inject another memory (normally automatic) ────────────────────────
    engine.memory_store.save(MemoryEntry(
        session_id=session.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        type=MemoryType.RUMOR,
        title="Something sealed in the Archive",
        content="Lyra implied that whatever closed the Archive twelve years ago was not a structural failure. The true reason appears to be classified.",
        entities=["Lyra Ashveil", "Old Archive"],
        location="Tallow & Ink tavern, Crosshaven",
        tags=["archive", "secret", "conspiracy"],
        importance=ImportanceLevel.HIGH,
        confidence=0.7,
    ))

    # ── Adjust relationship after two turns ───────────────────────────────
    engine.adjust_relationship(
        session.id,
        source="Lyra Ashveil",
        target="Player",
        trust=0.15,    # slight trust gained from the interaction
        respect=0.1,   # slight respect for knowing to seek her out
    )

    # ── Turn 3: Demonstrate memory recall ─────────────────────────────────
    separator("Turn 3 — Memory Recall")
    user3 = "You mentioned earlier that the Archive closure wasn't structural. What really happened?"
    print(f"You: {user3}\n")
    response3 = engine.chat(session.id, user3)
    print(f"Lyra: {response3}")

    # ── Developer inspection ───────────────────────────────────────────────
    separator("Developer Tools — Memory State")
    memories = engine.get_memories(session.id)
    print_memories(memories, title=f"Memories after 3 turns")

    separator("Developer Tools — Scene State")
    scene = engine.get_scene(session.id)
    print_scene(scene)

    separator("Developer Tools — Relationship State")
    rels = engine.get_relationships(session.id)
    if rels:
        print_relationships(rels)
    else:
        print("(no relationships tracked yet)")

    # ── Demonstrate persistence ────────────────────────────────────────────
    separator("Demonstrating Persistence")
    print(f"Session ID: {session.id}")
    print(f"Turn count: {engine.load_session(session.id).turn_count}")
    print(f"Memories stored: {engine.memory_store.count(session.id)}")
    print("\nYou can resume this session at any time with:")
    print(f"  python -m app.main chat --session {session.id[:8]}")
    print("\nAll state is stored in:", config.db_path)

    separator("Session Complete")


if __name__ == "__main__":
    main()
