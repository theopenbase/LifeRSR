"""
CLI entry point — the `kb` command.

Commands:
  kb recall <query>    — Recall notes from Get笔记 via search API
  kb ingest <file>     — Ingest a WeChat chat file or photo
  kb distill [--all]   — Distill inbox notes into structured knowledge
  kb review            — Review staged (low-confidence) notes
  kb query <keyword>   — Search the knowledge base
  kb status            — Show knowledge base statistics

  ┌─────────┐  recall   ┌───────────┐  distill  ┌────────────┐
  │ biji.com│ ────────▶ │  inbox/   │ ────────▶ │ knowledge/ │ (high)
  └─────────┘           └───────────┘           ├────────────┤
  ┌─────────┐  ingest                           │  staging/  │ (med/low)
  │ file    │ ────────▶                         └────────────┘
  └─────────┘                                      │ review
                                                   ▼
                                               approve / reject
"""

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .store import Note, save_note, load_note, list_notes, query_notes, count_notes

# Default data directory layout
DATA_DIR = Path(os.environ.get("KB_DATA_DIR", "data"))
INBOX_DIR = DATA_DIR / "inbox"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
STAGING_DIR = DATA_DIR / "staging"
STATE_DB = DATA_DIR / ".state.db"

console = Console()


def _load_env():
    """Load .env file if present (best-effort, no dependency)."""
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


@click.group()
def cli():
    """LifeRSR — Real to Simulation to Real. Agent-Native Personal Knowledge Base (AI 参谋知识库)"""
    _load_env()


# ──────────────────────────────────────────────
#  kb recall
# ──────────────────────────────────────────────

@cli.command()
@click.argument("query")
@click.option("--top-k", "-k", default=10, help="Max results to return.")
@click.option("--save/--no-save", default=True, help="Save recalled notes to inbox.")
def recall(query: str, top_k: int, save: bool):
    """Recall notes from Get笔记 via search API.

    Example:
        kb recall "AI教育" --top-k 5
    """
    from .getnote import GetNoteClient, SyncState, load_config

    try:
        config = load_config()
    except Exception as e:
        console.print(f"[red]配置错误:[/red] {e}")
        sys.exit(1)

    config.top_k = top_k
    inbox_getnote = INBOX_DIR / "getnote"
    inbox_getnote.mkdir(parents=True, exist_ok=True)

    with GetNoteClient(config) as client, SyncState(STATE_DB) as state:
        try:
            notes = client.recall(query, top_k=top_k)
        except Exception as e:
            console.print(f"[red]API 调用失败:[/red] {e}")
            sys.exit(1)

        state.log_recall(query, len(notes))

        new_count = 0
        updated_count = 0
        skipped_count = 0

        for recalled in notes:
            note_id = f"getnote-{recalled.id}"

            if not save:
                console.print(f"  [dim]{recalled.title}[/dim] (score: {recalled.score:.2f})")
                continue

            if state.is_synced(note_id) and not state.has_changed(note_id, recalled.content):
                skipped_count += 1
                continue

            is_update = state.is_synced(note_id)
            note = Note(
                id=note_id,
                source="getnote",
                title=recalled.title,
                content=recalled.content,
                created=_now_iso(),
                synced=_now_iso(),
            )
            save_note(note, inbox_getnote)
            state.mark_synced(note_id, "getnote", recalled.content)

            if is_update:
                updated_count += 1
            else:
                new_count += 1

        console.print(f"\n[bold]Recall 完成:[/bold] query=\"{query}\"")
        console.print(f"  API 返回: {len(notes)} 条笔记")
        if save:
            console.print(f"  新增: {new_count} | 更新: {updated_count} | 跳过: {skipped_count}")
        console.print(f"  保存位置: {inbox_getnote}/")


# ──────────────────────────────────────────────
#  kb ingest
# ──────────────────────────────────────────────

@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--context", "-c", default="", help="Conversation context (e.g., group name).")
@click.option("--source", "-s", type=click.Choice(["wechat", "photo", "auto"]), default="auto",
              help="Source type (auto-detect by default).")
def ingest(filepath: str, context: str, source: str):
    """Ingest a WeChat chat file or photo into the inbox.

    Examples:
        kb ingest chat.txt --source wechat --context "工作群"
        kb ingest screenshot.png --source photo
        kb ingest document.jpg   # auto-detects as photo
    """
    filepath = Path(filepath)

    # Auto-detect source type
    if source == "auto":
        photo_exts = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
        if filepath.suffix.lower() in photo_exts:
            source = "photo"
        else:
            source = "wechat"

    if source == "wechat":
        _ingest_wechat(filepath, context)
    elif source == "photo":
        _ingest_photo(filepath)


def _ingest_wechat(filepath: Path, context: str):
    """Ingest a WeChat text file."""
    from .wechat import WeChatImporter

    inbox_wechat = INBOX_DIR / "wechat"
    importer = WeChatImporter(inbox_wechat)

    try:
        note = importer.ingest_file(filepath, context=context)
    except Exception as e:
        console.print(f"[red]解析失败:[/red] {e}")
        sys.exit(1)

    if note:
        console.print(f"[green]导入成功:[/green] {note.title}")
        console.print(f"  ID: {note.id}")
        console.print(f"  保存位置: {inbox_wechat}/")
    else:
        console.print("[yellow]文件内容为空，跳过。[/yellow]")


def _ingest_photo(filepath: Path):
    """Ingest a photo or screenshot."""
    from .photo import PhotoImporter

    inbox_photo = INBOX_DIR / "photo"

    try:
        importer = PhotoImporter(inbox_photo)
    except ValueError as e:
        console.print(f"[red]配置错误:[/red] {e}")
        sys.exit(1)

    try:
        note = importer.process_photo(filepath)
    except FileNotFoundError as e:
        console.print(f"[red]文件未找到:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]处理失败:[/red] {e}")
        sys.exit(1)

    if note:
        console.print(f"[green]照片导入成功:[/green] {note.title}")
        console.print(f"  ID: {note.id}")
        console.print(f"  保存位置: {inbox_photo}/")
    else:
        console.print("[yellow]不支持的格式或文件过大，跳过。[/yellow]")


# ──────────────────────────────────────────────
#  kb distill
# ──────────────────────────────────────────────

@cli.command()
@click.option("--all", "distill_all", is_flag=True, help="Distill all inbox notes.")
@click.option("--source", "-s", type=click.Choice(["getnote", "wechat", "photo"]),
              help="Only distill from a specific source.")
@click.option("--dry-run", is_flag=True, help="Preview without saving.")
def distill(distill_all: bool, source: str, dry_run: bool):
    """Distill inbox notes into structured knowledge via Claude API.

    High-confidence results go to knowledge/.
    Medium/low-confidence go to staging/ for review.

    Examples:
        kb distill --all
        kb distill --source getnote
        kb distill --dry-run
    """
    from .distill import Distiller, DistillError
    from .staging import StagingManager

    # Collect inbox notes
    inbox_notes = []
    if source:
        source_dir = INBOX_DIR / source
        inbox_notes = list_notes(source_dir)
    elif distill_all:
        for sub in INBOX_DIR.iterdir() if INBOX_DIR.exists() else []:
            if sub.is_dir():
                inbox_notes.extend(list_notes(sub))
    else:
        # Default: distill all sources
        for sub in INBOX_DIR.iterdir() if INBOX_DIR.exists() else []:
            if sub.is_dir():
                inbox_notes.extend(list_notes(sub))

    if not inbox_notes:
        console.print("[yellow]收件箱为空，没有需要蒸馏的笔记。[/yellow]")
        console.print("  运行 `kb recall <query>` 或 `kb ingest <file>` 先导入内容。")
        return

    console.print(f"[bold]开始蒸馏:[/bold] {len(inbox_notes)} 条笔记\n")

    try:
        distiller = Distiller()
    except DistillError as e:
        console.print(f"[red]初始化失败:[/red] {e}")
        sys.exit(1)

    staging = StagingManager(STAGING_DIR, KNOWLEDGE_DIR)

    high_count = 0
    staging_count = 0
    error_count = 0

    with distiller:
        for i, note in enumerate(inbox_notes, 1):
            console.print(f"  [{i}/{len(inbox_notes)}] {note.title[:50]}...", end=" ")

            try:
                enriched = distiller.distill_note(note)
            except DistillError as e:
                console.print(f"[red]失败[/red]: {e}")
                error_count += 1
                continue

            if dry_run:
                console.print(
                    f"[dim]{enriched.category}[/dim] | "
                    f"[dim]{enriched.confidence}[/dim] | "
                    f"{enriched.summary}"
                )
                continue

            # Route by confidence
            if enriched.confidence == "high":
                save_note(enriched, KNOWLEDGE_DIR)
                console.print(f"[green]✓ knowledge/[/green] ({enriched.category})")
                high_count += 1
            else:
                save_note(enriched, STAGING_DIR)
                console.print(
                    f"[yellow]→ staging/[/yellow] "
                    f"({enriched.category}, {enriched.confidence})"
                )
                staging_count += 1

    console.print(f"\n[bold]蒸馏完成:[/bold]")
    if not dry_run:
        console.print(f"  → knowledge/: {high_count} (高置信度)")
        console.print(f"  → staging/:   {staging_count} (待审核)")
    if error_count:
        console.print(f"  [red]× 失败: {error_count}[/red]")
    if staging_count > 0:
        console.print(f"\n  运行 `kb review` 审核 staging 中的笔记。")


# ──────────────────────────────────────────────
#  kb review
# ──────────────────────────────────────────────

@cli.command()
@click.option("--approve-all", is_flag=True, help="Approve all staged notes.")
def review(approve_all: bool):
    """Review staged (low-confidence) notes.

    Interactively approve or reject each note, or use --approve-all.

    Examples:
        kb review
        kb review --approve-all
    """
    from .staging import StagingManager

    staging = StagingManager(STAGING_DIR, KNOWLEDGE_DIR)
    pending = staging.pending()

    if not pending:
        console.print("[green]没有待审核的笔记。[/green]")
        return

    if approve_all:
        count = staging.approve_all()
        console.print(f"[green]已批准 {count} 条笔记 → knowledge/[/green]")
        return

    console.print(f"[bold]待审核: {len(pending)} 条笔记[/bold]\n")

    approved = 0
    rejected = 0

    for i, note in enumerate(pending, 1):
        console.print(f"\n{'─' * 60}")
        console.print(f"[bold][{i}/{len(pending)}] {note.title}[/bold]")
        if note.category:
            console.print(f"  分类: {note.category} | 置信度: {note.confidence}")
        if note.tags:
            console.print(f"  标签: {', '.join(note.tags)}")
        if note.summary:
            console.print(f"  摘要: {note.summary}")
        console.print()

        # Show a content preview (first 200 chars)
        preview = note.content[:200]
        if len(note.content) > 200:
            preview += "..."
        console.print(f"  {preview}")
        console.print()

        action = click.prompt(
            "  操作",
            type=click.Choice(["a", "r", "s", "q"]),
            default="s",
            show_choices=True,
            prompt_suffix=" (a=approve, r=reject, s=skip, q=quit): ",
        )

        if action == "a":
            staging.approve(note.id)
            console.print(f"  [green]✓ 已批准 → knowledge/[/green]")
            approved += 1
        elif action == "r":
            staging.reject(note.id)
            console.print(f"  [red]× 已拒绝（已删除）[/red]")
            rejected += 1
        elif action == "q":
            break
        # 's' = skip, do nothing

    console.print(f"\n[bold]审核完成:[/bold] 批准 {approved} | 拒绝 {rejected}")
    remaining = staging.pending_count()
    if remaining > 0:
        console.print(f"  剩余待审核: {remaining}")


# ──────────────────────────────────────────────
#  kb query
# ──────────────────────────────────────────────

@cli.command()
@click.argument("keyword")
@click.option("--source", "-s", type=click.Choice(["knowledge", "inbox", "staging", "all"]),
              default="knowledge", help="Where to search.")
def query(keyword: str, source: str):
    """Search the knowledge base by keyword.

    Examples:
        kb query "AI教育"
        kb query "张三" --source all
    """
    search_dirs = []

    if source in ("knowledge", "all"):
        search_dirs.append(("knowledge", KNOWLEDGE_DIR))
    if source in ("staging", "all"):
        search_dirs.append(("staging", STAGING_DIR))
    if source in ("inbox", "all"):
        if INBOX_DIR.exists():
            for sub in INBOX_DIR.iterdir():
                if sub.is_dir():
                    search_dirs.append((f"inbox/{sub.name}", sub))

    all_results = []
    for label, directory in search_dirs:
        results = query_notes(directory, keyword)
        for note in results:
            all_results.append((label, note))

    if not all_results:
        console.print(f"[yellow]没有找到匹配 \"{keyword}\" 的笔记。[/yellow]")
        return

    table = Table(title=f"搜索结果: \"{keyword}\" ({len(all_results)} 条)")
    table.add_column("位置", style="cyan", width=15)
    table.add_column("标题", width=30)
    table.add_column("分类", width=10)
    table.add_column("标签", width=20)
    table.add_column("摘要", width=40)

    for label, note in all_results:
        table.add_row(
            label,
            note.title[:30],
            note.category or "-",
            ", ".join(note.tags[:3]) if note.tags else "-",
            note.summary[:40] if note.summary else "-",
        )

    console.print(table)


# ──────────────────────────────────────────────
#  kb status
# ──────────────────────────────────────────────

@cli.command()
def status():
    """Show knowledge base statistics.

    Example:
        kb status
    """
    console.print("[bold]TheOpenBase 状态[/bold]\n")

    # Count notes in each directory
    sections = [
        ("knowledge/", KNOWLEDGE_DIR, "green"),
        ("staging/", STAGING_DIR, "yellow"),
    ]

    # Inbox sub-directories
    inbox_total = 0
    if INBOX_DIR.exists():
        for sub in sorted(INBOX_DIR.iterdir()):
            if sub.is_dir():
                count = count_notes(sub)
                inbox_total += count
                sections.append((f"inbox/{sub.name}/", sub, "blue"))

    table = Table()
    table.add_column("目录", style="bold", width=25)
    table.add_column("笔记数", justify="right", width=10)

    for label, directory, color in sections:
        count = count_notes(directory)
        table.add_row(f"[{color}]{label}[/{color}]", str(count))

    console.print(table)

    # Sync state stats
    if STATE_DB.exists():
        from .getnote import SyncState
        with SyncState(STATE_DB) as state:
            stats = state.stats()
            console.print(f"\n[bold]同步状态 (.state.db):[/bold]")
            console.print(f"  已同步笔记: {stats['synced_notes']}")
            console.print(f"  Recall 查询次数: {stats['recall_queries']}")

    # Staging review reminder
    staging_count = count_notes(STAGING_DIR)
    if staging_count > 0:
        console.print(f"\n[yellow]⚠ {staging_count} 条笔记待审核。运行 `kb review` 处理。[/yellow]")

    console.print(f"\n[dim]数据目录: {DATA_DIR.resolve()}[/dim]")


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
