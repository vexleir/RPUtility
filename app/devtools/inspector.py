"""
Developer inspection tools.
Provides rich terminal output for inspecting all stored state:
memory, scene, relationships, sessions, and prompts.
"""

from __future__ import annotations

from app.core.models import (
    MemoryEntry,
    SceneState,
    RelationshipState,
    Session,
    WorldStateEntry,
    ContradictonFlag,
)


try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


def _console() -> "Console":
    if _HAS_RICH:
        return Console()
    raise RuntimeError("rich is not installed. Run: pip install rich")


# ── Memory inspection ─────────────────────────────────────────────────────────

def print_memories(memories: list[MemoryEntry], title: str = "Stored Memories") -> None:
    if not _HAS_RICH:
        _plain_memories(memories, title)
        return

    console = _console()
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_lines=True,
        expand=True,
    )
    table.add_column("Type", style="cyan", width=16)
    table.add_column("Importance", style="yellow", width=10)
    table.add_column("Title", style="bold", width=24)
    table.add_column("Content", width=45)
    table.add_column("Entities", style="green", width=18)
    table.add_column("Created", style="dim", width=12)

    for m in memories:
        importance_style = {
            "low": "dim",
            "medium": "white",
            "high": "yellow",
            "critical": "bold red",
        }.get(m.importance.value, "white")

        table.add_row(
            m.type.value,
            Text(m.importance.value, style=importance_style),
            m.title,
            m.content[:100] + ("…" if len(m.content) > 100 else ""),
            ", ".join(m.entities[:3]),
            m.created_at.strftime("%Y-%m-%d"),
        )

    console.print(table)
    console.print(f"[dim]Total: {len(memories)} memories[/dim]")


def _plain_memories(memories: list[MemoryEntry], title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    for m in memories:
        print(f"[{m.type.value.upper()}] [{m.importance.value}] {m.title}")
        print(f"  {m.content}")
        if m.entities:
            print(f"  Entities: {', '.join(m.entities)}")
        print()
    print(f"Total: {len(memories)}")


# ── Scene inspection ──────────────────────────────────────────────────────────

def print_scene(scene: SceneState) -> None:
    if not _HAS_RICH:
        print(f"\n[SCENE]\nLocation: {scene.location}")
        print(f"Characters: {', '.join(scene.active_characters)}")
        print(f"Summary: {scene.summary}")
        return

    console = _console()
    chars = ", ".join(scene.active_characters) if scene.active_characters else "None"
    content = (
        f"[bold]Location:[/bold] {scene.location}\n"
        f"[bold]Characters:[/bold] {chars}\n"
        f"[bold]Summary:[/bold] {scene.summary or '(no summary yet)'}\n"
        f"[dim]Last updated: {scene.last_updated.strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
    )
    console.print(Panel(content, title="[cyan]Current Scene[/cyan]", expand=False))


# ── Relationship inspection ───────────────────────────────────────────────────

def print_relationships(rels: list[RelationshipState], title: str = "Relationships") -> None:
    if not _HAS_RICH:
        _plain_relationships(rels, title)
        return

    console = _console()
    table = Table(title=title, box=box.ROUNDED)
    table.add_column("From", style="cyan")
    table.add_column("To", style="cyan")
    table.add_column("Trust", justify="right")
    table.add_column("Affection", justify="right")
    table.add_column("Respect", justify="right")
    table.add_column("Fear", justify="right")
    table.add_column("Hostility", justify="right")

    for r in rels:
        table.add_row(
            r.source_entity,
            r.target_entity,
            _fmt_axis(r.trust, symmetric=True),
            _fmt_axis(r.affection, symmetric=True),
            _fmt_axis(r.respect, symmetric=True),
            _fmt_axis(r.fear, symmetric=False),
            _fmt_axis(r.hostility, symmetric=False),
        )

    console.print(table)


def _fmt_axis(value: float, symmetric: bool) -> str:
    bar_len = 5
    if symmetric:
        # Map -1..1 → 0..10 filled chars
        filled = round((value + 1) / 2 * bar_len)
        return f"{'█' * filled}{'░' * (bar_len - filled)} {value:+.2f}"
    else:
        filled = round(value * bar_len)
        return f"{'█' * filled}{'░' * (bar_len - filled)} {value:.2f}"


def _plain_relationships(rels: list[RelationshipState], title: str) -> None:
    print(f"\n{title}")
    for r in rels:
        print(
            f"  {r.source_entity} → {r.target_entity}: "
            f"trust={r.trust:+.2f} affection={r.affection:+.2f} "
            f"respect={r.respect:+.2f} fear={r.fear:.2f} hostility={r.hostility:.2f}"
        )


# ── Session inspection ────────────────────────────────────────────────────────

def print_sessions(sessions: list[Session]) -> None:
    if not _HAS_RICH:
        for s in sessions:
            print(f"[{s.id[:8]}] {s.name} | char: {s.character_name} | turns: {s.turn_count}")
        return

    console = _console()
    table = Table(title="Sessions", box=box.ROUNDED)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Name", style="bold")
    table.add_column("Character")
    table.add_column("Lorebook", style="dim")
    table.add_column("Turns", justify="right")
    table.add_column("Last Active")

    for s in sessions:
        table.add_row(
            s.id[:8] + "…",
            s.name,
            s.character_name,
            s.lorebook_name or "—",
            str(s.turn_count),
            s.last_active.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


# ── World-state inspection ────────────────────────────────────────────────────

def print_world_state(entries: list[WorldStateEntry], title: str = "World State") -> None:
    if not _HAS_RICH:
        print(f"\n{title}")
        for e in entries:
            imp = " [CRITICAL]" if e.importance.value == "critical" else ""
            print(f"  [{e.category}] {e.title}{imp}: {e.content}")
        return

    console = _console()
    table = Table(title=title, box=box.ROUNDED, show_lines=True, expand=True)
    table.add_column("Category", style="cyan", width=16)
    table.add_column("Importance", style="yellow", width=10)
    table.add_column("Title", style="bold", width=24)
    table.add_column("Content", width=50)
    table.add_column("Updated", style="dim", width=12)

    for e in entries:
        imp_style = "bold red" if e.importance.value == "critical" else "white"
        table.add_row(
            e.category,
            Text(e.importance.value, style=imp_style),
            e.title,
            e.content[:100] + ("…" if len(e.content) > 100 else ""),
            e.updated_at.strftime("%Y-%m-%d"),
        )

    console.print(table)
    console.print(f"[dim]Total: {len(entries)} entries[/dim]")


# ── Contradiction flags inspection ────────────────────────────────────────────

def print_contradiction_flags(flags: list[ContradictonFlag], title: str = "Contradiction Flags") -> None:
    if not _HAS_RICH:
        print(f"\n{title}")
        for f in flags:
            print(f"  [{f.detected_at.strftime('%Y-%m-%d %H:%M')}] {f.description}")
            print(f"    Resolution: {f.resolution}")
        return

    console = _console()
    table = Table(title=title, box=box.ROUNDED, show_lines=True, expand=True)
    table.add_column("Detected", style="dim", width=18)
    table.add_column("Description", width=50)
    table.add_column("Resolution", style="yellow", width=18)

    for f in flags:
        table.add_row(
            f.detected_at.strftime("%Y-%m-%d %H:%M"),
            f.description,
            f.resolution,
        )

    console.print(table)
    console.print(f"[dim]Total: {len(flags)} flags[/dim]")


# ── Prompt inspection ─────────────────────────────────────────────────────────

def print_prompt(messages: list[dict]) -> None:
    if not _HAS_RICH:
        from app.prompting.builder import format_prompt_debug
        print(format_prompt_debug(messages))
        return

    console = _console()
    console.rule("[bold cyan]Full Prompt[/bold cyan]")
    for msg in messages:
        role = msg["role"].upper()
        content = msg["content"]
        style = {
            "SYSTEM": "blue",
            "USER": "green",
            "ASSISTANT": "yellow",
        }.get(role, "white")
        console.print(Panel(
            content,
            title=f"[{style}]{role}[/{style}]",
            border_style=style,
            expand=True,
        ))
    console.rule()
