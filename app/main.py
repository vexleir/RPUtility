"""
RP Utility — main CLI entry point.

Commands:
  chat    Start or resume an interactive roleplay session
  new     Create a new session
  sessions List all sessions
  memory  Inspect stored memories for a session
  scene   View or update scene state
  rels    View relationship state
  inspect Show the full prompt for a session (last turn)
  check   Verify provider connectivity

Usage examples:
  python -m app.main new --name "Forest Adventure" --char "Lyra" --lorebook "Elven Wilds"
  python -m app.main chat --session <id>
  python -m app.main memory --session <id>
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import config
from app.core.engine import RoleplayEngine
from app.devtools.inspector import (
    print_memories,
    print_scene,
    print_relationships,
    print_sessions,
)


def _engine() -> RoleplayEngine:
    return RoleplayEngine(config)


# ─── CLI group ────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """RP Utility — local-first AI roleplay with persistent memory."""
    pass


# ─── check ────────────────────────────────────────────────────────────────────

@cli.command()
def check():
    """Check if the configured model provider is reachable."""
    engine = _engine()
    available = engine.provider.is_available()
    if available:
        click.echo(f"✓ Provider '{config.provider}' is reachable.")
        click.echo(f"  Default model: {config.active_model()}")
        models = engine.list_available_models()
        if models:
            click.echo(f"  Downloaded models: {len(models)}")
            click.echo(f"  Run 'python -m app.main models' to see the full list.")
    else:
        click.echo(
            f"✗ Provider '{config.provider}' is NOT reachable.\n"
            f"  Make sure your provider is running:\n"
            f"    Ollama:    ollama serve\n"
            f"    LM Studio: start the local server in the app"
        )
        sys.exit(1)


# ─── models ───────────────────────────────────────────────────────────────────

@cli.command("models")
def list_models():
    """List all models available on the configured provider."""
    engine = _engine()

    if not engine.provider.is_available():
        click.echo(
            f"✗ Provider '{config.provider}' is not reachable. Is it running?"
        )
        sys.exit(1)

    models = engine.list_available_models()
    if not models:
        click.echo("No models found.")
        if config.provider == "ollama":
            click.echo("  Pull a model with: ollama pull <name>")
            click.echo("  Example: ollama pull llama3.2")
        return

    _print_models(models, config.provider, config.active_model())


def _print_models(models: list[dict], provider: str, active_model: str) -> None:
    """Print a table of available models."""
    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box

        console = Console()
        table = Table(
            title=f"Available Models ({provider})",
            box=box.ROUNDED,
            show_lines=False,
        )
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Model Name", style="bold")
        table.add_column("Size", justify="right", style="cyan")
        table.add_column("Modified", style="dim")
        table.add_column("Active", justify="center")

        for i, m in enumerate(models, 1):
            name = m.get("name") or m.get("id", "unknown")
            size_bytes = m.get("size", 0)
            size_str = _fmt_size(size_bytes) if size_bytes else "—"
            modified = m.get("modified_at", m.get("created", ""))[:10]  # date only
            is_active = "●" if name == active_model or name.split(":")[0] == active_model else ""
            style = "bold green" if is_active else ""
            table.add_row(
                str(i),
                name,
                size_str,
                modified,
                is_active,
                style=style,
            )

        console.print(table)
        console.print(
            f"\n[dim]Default model (from config): {active_model}[/dim]\n"
            f"[dim]Use --model <name> when creating a session to choose a different model.[/dim]"
        )

    except ImportError:
        # Fallback without rich
        click.echo(f"\nAvailable models ({provider}):")
        for i, m in enumerate(models, 1):
            name = m.get("name") or m.get("id", "unknown")
            size_bytes = m.get("size", 0)
            size_str = _fmt_size(size_bytes) if size_bytes else ""
            active = " ◄ active" if name == active_model else ""
            click.echo(f"  {i:>2}. {name:<40} {size_str}{active}")
        click.echo(f"\nDefault model: {active_model}")
        click.echo("Use --model <name> when creating a session.")


def _fmt_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ─── new ──────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--name", "-n", required=True, help="Session name")
@click.option("--char", "-c", required=True, help="Character name (must match a loaded card)")
@click.option("--lorebook", "-l", default=None, help="Lorebook name to attach")
@click.option("--location", default="Unknown", help="Starting location")
@click.option(
    "--model", "-m", default=None,
    help="Model to use for this session (overrides config). "
         "Omit to pick interactively from downloaded models.",
)
@click.option(
    "--pick-model", is_flag=True, default=False,
    help="Interactively choose a model from the downloaded list.",
)
def new(name: str, char: str, lorebook: str | None, location: str, model: str | None, pick_model: bool):
    """Create a new roleplay session."""
    engine = _engine()

    # Ensure card is available
    available_cards = engine.list_cards()
    if char not in available_cards:
        click.echo(
            f"✗ Character card '{char}' not found.\n"
            f"  Available cards: {available_cards or ['(none — add .json files to data/cards/)']}"
        )
        sys.exit(1)

    # ── Model selection ───────────────────────────────────────────────────
    chosen_model: str | None = model

    if pick_model and not model:
        chosen_model = _pick_model_interactively(engine)
        if chosen_model is None:
            click.echo("No model selected — using the default from config.")

    if chosen_model:
        # Validate that the model actually exists on the provider
        available = engine.list_available_models()
        available_names = [m.get("name") or m.get("id", "") for m in available]
        if available_names and chosen_model not in available_names:
            # Try prefix match (e.g. "llama3.2" matches "llama3.2:latest")
            prefix_match = next(
                (n for n in available_names if n.split(":")[0] == chosen_model), None
            )
            if prefix_match:
                chosen_model = prefix_match
            else:
                click.echo(
                    f"⚠ Model '{chosen_model}' not found on provider.\n"
                    f"  Available: {', '.join(available_names) or '(none)'}\n"
                    f"  Proceeding anyway — generation may fail."
                )

    session = engine.new_session(
        name=name,
        character_name=char,
        lorebook_name=lorebook,
        initial_location=location,
        initial_characters=[char],
        model_name=chosen_model,
    )
    click.echo(f"✓ Session created: {session.id}")
    click.echo(f"  Name:      {session.name}")
    click.echo(f"  Character: {session.character_name}")
    click.echo(f"  Lorebook:  {session.lorebook_name or '(none)'}")
    click.echo(f"  Model:     {session.model_name or config.active_model() + ' (default)'}")
    click.echo(f"\nStart chatting with:")
    click.echo(f"  python -m app.main chat --session {session.id}")


def _pick_model_interactively(engine: RoleplayEngine) -> str | None:
    """
    Show the list of downloaded models and let the user pick one by number.
    Returns the chosen model name, or None if cancelled / unavailable.
    """
    if not engine.provider.is_available():
        click.echo("Provider not reachable — cannot list models.")
        return None

    models = engine.list_available_models()
    if not models:
        click.echo("No models found on provider.")
        return None

    click.echo("\nAvailable models:")
    for i, m in enumerate(models, 1):
        name = m.get("name") or m.get("id", "unknown")
        size_bytes = m.get("size", 0)
        size_str = f"  ({_fmt_size(size_bytes)})" if size_bytes else ""
        click.echo(f"  {i:>2}. {name}{size_str}")

    default_model = config.active_model()
    click.echo(f"\n  0. Use default ({default_model})")

    while True:
        try:
            raw = click.prompt("\nSelect model", default="0")
            choice = int(raw)
        except (ValueError, click.Abort):
            return None

        if choice == 0:
            return None
        if 1 <= choice <= len(models):
            m = models[choice - 1]
            return m.get("name") or m.get("id")
        click.echo(f"  Enter a number between 0 and {len(models)}.")


# ─── sessions ─────────────────────────────────────────────────────────────────

@cli.command("sessions")
def list_sessions():
    """List all roleplay sessions."""
    engine = _engine()
    sessions = engine.list_sessions()
    if not sessions:
        click.echo("No sessions found. Create one with: python -m app.main new")
        return
    print_sessions(sessions)


# ─── chat ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--session", "-s", required=True, help="Session ID to resume")
@click.option("--stream", is_flag=True, default=False, help="Stream output token by token")
@click.option("--show-prompt", is_flag=True, default=False, help="Show the full prompt before each response")
def chat(session: str, stream: bool, show_prompt: bool):
    """Start an interactive roleplay chat session."""
    engine = _engine()

    # Allow abbreviated IDs (first 8 chars)
    resolved_id = _resolve_session_id(engine, session)
    if not resolved_id:
        click.echo(f"✗ Session '{session}' not found.")
        sys.exit(1)

    sess = engine.load_session(resolved_id)
    scene = engine.get_scene(resolved_id)
    card = engine.get_card(sess.character_name)

    if show_prompt:
        config.show_prompt = True

    click.echo(f"\n{'='*60}")
    click.echo(f"  {sess.name}")
    click.echo(f"  Character: {sess.character_name}  |  Location: {scene.location}")
    click.echo(f"  Turns: {sess.turn_count}")
    click.echo(f"  Type /quit to exit, /scene to view scene, /memory to view memories")
    click.echo(f"{'='*60}\n")

    # Show first message if this is a new session (turn 0)
    if sess.turn_count == 0 and card and card.first_message:
        click.echo(f"{sess.character_name}: {card.first_message}\n")

    while True:
        try:
            user_input = click.prompt("You", prompt_suffix="> ").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\nGoodbye!")
            break

        if not user_input:
            continue

        # ── Slash commands ─────────────────────────────────────────────
        if user_input.startswith("/"):
            _handle_slash_command(user_input, engine, resolved_id)
            continue

        # ── Normal chat turn ───────────────────────────────────────────
        try:
            response = engine.chat(resolved_id, user_input, stream=stream)
            if not stream:
                click.echo(f"\n{sess.character_name}: {response}\n")
        except RuntimeError as e:
            click.echo(f"\n[ERROR] {e}\n")
        except Exception as e:
            click.echo(f"\n[UNEXPECTED ERROR] {e}\n")
            if config.debug:
                import traceback
                traceback.print_exc()


def _handle_slash_command(cmd: str, engine: RoleplayEngine, session_id: str) -> None:
    """Handle in-chat slash commands."""
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if command == "/quit" or command == "/exit":
        click.echo("Goodbye!")
        sys.exit(0)

    elif command == "/memory":
        memories = engine.get_memories(session_id)
        print_memories(memories)

    elif command == "/scene":
        scene = engine.get_scene(session_id)
        print_scene(scene)

    elif command == "/rels" or command == "/relationships":
        rels = engine.get_relationships(session_id)
        print_relationships(rels)

    elif command == "/location":
        if args:
            engine.update_scene(session_id, location=args)
            click.echo(f"Location updated to: {args}")
        else:
            scene = engine.get_scene(session_id)
            click.echo(f"Current location: {scene.location}")

    elif command == "/debug":
        config.debug = not config.debug
        click.echo(f"Debug mode: {'ON' if config.debug else 'OFF'}")

    elif command == "/help":
        click.echo(
            "\nSlash commands:\n"
            "  /memory        View stored memories\n"
            "  /scene         View current scene state\n"
            "  /rels          View relationship states\n"
            "  /location <x>  Update current location\n"
            "  /debug         Toggle debug mode\n"
            "  /quit          Exit the session\n"
        )

    else:
        click.echo(f"Unknown command: {command}. Type /help for available commands.")


# ─── memory ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--session", "-s", required=True, help="Session ID")
def memory(session: str):
    """Inspect stored memories for a session."""
    engine = _engine()
    resolved = _resolve_session_id(engine, session)
    if not resolved:
        click.echo(f"✗ Session '{session}' not found.")
        sys.exit(1)

    sess = engine.load_session(resolved)
    memories = engine.get_memories(resolved)
    print_memories(memories, title=f"Memories — {sess.name}")


# ─── scene ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--session", "-s", required=True, help="Session ID")
@click.option("--location", default=None, help="Update location")
@click.option("--summary", default=None, help="Update scene summary")
def scene(session: str, location: str | None, summary: str | None):
    """View or update scene state for a session."""
    engine = _engine()
    resolved = _resolve_session_id(engine, session)
    if not resolved:
        click.echo(f"✗ Session '{session}' not found.")
        sys.exit(1)

    if location or summary:
        engine.update_scene(resolved, location=location, summary=summary)
        click.echo("Scene updated.")

    sc = engine.get_scene(resolved)
    print_scene(sc)


# ─── rels ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--session", "-s", required=True, help="Session ID")
def rels(session: str):
    """View relationship state for a session."""
    engine = _engine()
    resolved = _resolve_session_id(engine, session)
    if not resolved:
        click.echo(f"✗ Session '{session}' not found.")
        sys.exit(1)

    relationships = engine.get_relationships(resolved)
    print_relationships(relationships)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_session_id(engine: RoleplayEngine, partial_id: str) -> str | None:
    """
    Accept either a full UUID or an 8-char prefix.
    Returns the full session ID if found, else None.
    """
    sessions = engine.list_sessions()
    for s in sessions:
        if s.id == partial_id or s.id.startswith(partial_id):
            return s.id
    return None


# ─── serve ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to")
@click.option("--port", default=7860, show_default=True, help="Port to listen on")
@click.option("--reload", is_flag=True, default=False, help="Auto-reload on code changes (dev mode)")
def serve(host: str, port: int, reload: bool):
    """Start the web UI (open http://localhost:7860 in your browser)."""
    try:
        import uvicorn
    except ImportError:
        click.echo("✗ uvicorn is not installed. Run: pip install uvicorn[standard]")
        sys.exit(1)

    click.echo(f"Starting RP Utility web UI…")
    click.echo(f"  Open: http://{host}:{port}")
    click.echo(f"  Press Ctrl+C to stop.\n")

    uvicorn.run(
        "app.web.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",   # show requests + errors in the terminal
    )


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
