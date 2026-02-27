#!/usr/bin/env python3
"""
LLM Model Switcher – Automated & Polished

Scans your system for downloaded models from popular LLM backends (llama.cpp,
LM Studio, Jan.ai, etc.), presents an interactive selection menu with rich
formatting, and then copies or symlinks the chosen model to another backend's
model folder. Works on Windows and Linux.
"""

import os
import sys
import shutil
import platform
from pathlib import Path
from typing import List, Dict, Any, Optional

# Rich UI components
try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.prompt import Confirm
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# Interactive menus
try:
    import questionary
    HAS_QUESTIONARY = True
except ImportError:
    HAS_QUESTIONARY = False

# Fallback for no rich/questionary
if not HAS_RICH:
    # Simple print fallback
    def rprint(*args, **kwargs):
        print(*args, **kwargs)
    Console = None

# -------------------- Configuration --------------------
# Default search paths per backend (first path is the destination when switching)
BACKENDS = {
    "llama.cpp": {
        "paths": [],
        "extensions": [".gguf", ".bin"],
    },
    "LM Studio": {
        "paths": [],
        "extensions": [".gguf", ".bin"],
    },
    "Jan.ai": {
        "paths": [],
        "extensions": [".gguf"],
    },
}

# Populate with OS‑specific default locations
home = Path.home()
if platform.system() == "Windows":
    user_profile = Path(os.environ.get("USERPROFILE", ""))
    BACKENDS["llama.cpp"]["paths"] = [
        home / "models",
        home / "llama.cpp" / "models",
    ]
    BACKENDS["LM Studio"]["paths"] = [
        user_profile / ".lmstudio" / "models" if user_profile else home / ".lmstudio" / "models",
    ]
    BACKENDS["Jan.ai"]["paths"] = [
        user_profile / "jan" / "models" if user_profile else home / "jan" / "models",
    ]
else:  # Linux / macOS
    BACKENDS["llama.cpp"]["paths"] = [
        home / "models",
        home / "llama.cpp" / "models",
    ]
    BACKENDS["LM Studio"]["paths"] = [
        home / ".lmstudio" / "models",
    ]
    BACKENDS["Jan.ai"]["paths"] = [
        home / "jan" / "models",
    ]

# Allow overriding via environment variables (semicolon/colon separated)
for backend_name in BACKENDS:
    env_var = f"{backend_name.upper().replace(' ', '_')}_PATH"
    if env_var in os.environ:
        extra = os.environ[env_var].split(os.pathsep)
        BACKENDS[backend_name]["paths"].extend(Path(p) for p in extra)

# -------------------- Model Discovery --------------------
def discover_models() -> List[Dict[str, Any]]:
    """Walk through all backend directories and collect model files."""
    models = []
    console = Console() if HAS_RICH else None

    if console:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task("Scanning for models...", total=None)
            for backend_name, config in BACKENDS.items():
                for directory in config["paths"]:
                    if not directory.exists():
                        continue
                    for ext in config["extensions"]:
                        for model_path in directory.rglob(f"*{ext}"):
                            if model_path.is_file():
                                stat = model_path.stat()
                                models.append({
                                    "name": model_path.name,
                                    "path": str(model_path.absolute()),
                                    "backend": backend_name,
                                    "size": stat.st_size,
                                    "modified": stat.st_mtime,
                                })
            progress.update(task, completed=True)
    else:
        # Fallback without rich
        print("Scanning for models...")
        for backend_name, config in BACKENDS.items():
            for directory in config["paths"]:
                if not directory.exists():
                    continue
                for ext in config["extensions"]:
                    for model_path in directory.rglob(f"*{ext}"):
                        if model_path.is_file():
                            stat = model_path.stat()
                            models.append({
                                "name": model_path.name,
                                "path": str(model_path.absolute()),
                                "backend": backend_name,
                                "size": stat.st_size,
                                "modified": stat.st_mtime,
                            })
    return models

# -------------------- Display & Selection --------------------
def show_models_table(models: List[Dict[str, Any]]) -> None:
    """Display a rich table of discovered models."""
    if not HAS_RICH:
        return  # skip, selection menu will show basic info
    console = Console()
    table = Table(title="Discovered Models", show_lines=True)
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("Backend", style="magenta")
    table.add_column("Model Name", style="green")
    table.add_column("Size", justify="right", style="yellow")

    for idx, m in enumerate(models, 1):
        size_mb = m["size"] / (1024 * 1024)
        table.add_row(
            str(idx),
            m["backend"],
            m["name"],
            f"{size_mb:.1f} MB"
        )
    console.print(table)

def select_model_interactive(models: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Let user pick a model using questionary or fallback."""
    if not models:
        rprint("[red]No models found.[/red]")
        return None

    # Show rich table if available
    if HAS_RICH:
        show_models_table(models)

    if HAS_QUESTIONARY:
        choices = []
        for m in models:
            size_mb = m["size"] / (1024 * 1024)
            label = f"[{m['backend']}] {m['name']} ({size_mb:.1f} MB)"
            choices.append(questionary.Choice(title=label, value=m))
        answer = questionary.select(
            "Select a model:",
            choices=choices,
            use_shortcuts=True,
            qmark="🦙",
            style=questionary.Style([
                ('selected', 'fg:ansiblue bg:ansigray'),
                ('highlighted', 'fg:ansicyan bold'),
            ])
        ).ask()
        return answer
    else:
        # Simple numbered fallback
        print("\nAvailable models:")
        for i, m in enumerate(models, 1):
            size_mb = m["size"] / (1024 * 1024)
            print(f"{i:3}. [{m['backend']}] {m['name']} ({size_mb:.1f} MB)")
        print("0. Cancel")
        try:
            choice = int(input("\nEnter number: "))
            if 1 <= choice <= len(models):
                return models[choice-1]
        except ValueError:
            pass
        return None

def select_destination_backend(source_backend: str) -> Optional[str]:
    """Let user pick a destination backend (excluding source)."""
    dest_backends = [name for name in BACKENDS if name != source_backend]
    if not dest_backends:
        rprint("[red]No other backends configured.[/red]")
        return None

    if HAS_QUESTIONARY:
        answer = questionary.select(
            "Select destination backend:",
            choices=dest_backends,
            qmark="➡️",
        ).ask()
        return answer
    else:
        print("\nDestination backends:")
        for i, name in enumerate(dest_backends, 1):
            print(f"{i:3}. {name}")
        print("0. Cancel")
        try:
            choice = int(input("\nEnter number: "))
            if 1 <= choice <= len(dest_backends):
                return dest_backends[choice-1]
        except ValueError:
            pass
        return None

# -------------------- Switching Logic --------------------
def switch_model(model: Dict[str, Any], dest_backend: str, method: str = "copy") -> bool:
    """Copy or symlink model to destination backend's primary folder."""
    src_path = Path(model["path"])
    dest_dir = BACKENDS[dest_backend]["paths"][0]  # first path is destination
    dest_path = dest_dir / src_path.name

    # Create destination directory if needed
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        rprint(f"[red]Error creating destination directory: {e}[/red]")
        return False

    # Handle existing file
    if dest_path.exists():
        if HAS_QUESTIONARY:
            overwrite = questionary.confirm(
                f"File {dest_path} already exists. Overwrite?",
                default=False
            ).ask()
        else:
            resp = input(f"File {dest_path} already exists. Overwrite? (y/N): ").strip().lower()
            overwrite = resp == 'y'
        if not overwrite:
            rprint("[yellow]Skipping.[/yellow]")
            return False
        # Remove existing file/directory
        try:
            if dest_path.is_symlink() or dest_path.is_file():
                dest_path.unlink()
            elif dest_path.is_dir():
                shutil.rmtree(dest_path)
        except Exception as e:
            rprint(f"[red]Could not remove existing file: {e}[/red]")
            return False

    # Perform the switch
    try:
        if method == "symlink":
            if platform.system() == "Windows":
                # Try symlink, fallback to copy if it fails
                try:
                    os.symlink(src_path, dest_path)
                    rprint(f"[green]Symbolic link created: {dest_path}[/green]")
                except OSError:
                    rprint("[yellow]Symlink failed (maybe need admin/developer mode). Falling back to copy.[/yellow]")
                    shutil.copy2(src_path, dest_path)
                    rprint(f"[green]Copied to {dest_path}[/green]")
            else:
                os.symlink(src_path, dest_path)
                rprint(f"[green]Symbolic link created: {dest_path}[/green]")
        else:  # copy
            # Show progress bar if rich available
            if HAS_RICH:
                with Progress(
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                ) as progress:
                    task = progress.add_task("[cyan]Copying...", total=src_path.stat().st_size)
                    shutil.copy2(src_path, dest_path)
                    progress.update(task, completed=src_path.stat().st_size)
            else:
                shutil.copy2(src_path, dest_path)
            rprint(f"[green]Copied to {dest_path}[/green]")
        return True
    except Exception as e:
        rprint(f"[red]Error during switch: {e}[/red]")
        return False

# -------------------- Command Line Entry Point --------------------
def main():
    # Check for required libraries and show instructions if missing
    if not HAS_RICH or not HAS_QUESTIONARY:
        print("For the best experience, install optional dependencies:")
        print("  pip install rich questionary")
        if not HAS_RICH and not HAS_QUESTIONARY:
            print("Falling back to basic mode.\n")
        elif not HAS_RICH:
            print("Rich not installed; output will be less polished.\n")
        elif not HAS_QUESTIONARY:
            print("Questionary not installed; using basic menus.\n")

    # Discover models
    models = discover_models()
    if not models:
        rprint("[red]No models found. Check your backend paths or set environment variables like LLAMA_CPP_PATH.[/red]")
        sys.exit(1)

    # Select source model
    selected = select_model_interactive(models)
    if selected is None:
        rprint("[yellow]No model selected. Exiting.[/yellow]")
        sys.exit(0)

    # Select destination backend
    dest_backend = select_destination_backend(selected["backend"])
    if dest_backend is None:
        rprint("[yellow]No destination selected. Exiting.[/yellow]")
        sys.exit(0)

    # Choose copy or symlink (default copy for safety)
    method = "copy"
    if HAS_QUESTIONARY:
        method = questionary.select(
            "How would you like to switch?",
            choices=[
                questionary.Choice("Copy (safe, uses disk space)", value="copy"),
                questionary.Choice("Symlink (saves space, may need privileges)", value="symlink"),
            ],
            default="copy"
        ).ask()
        if method is None:
            method = "copy"
    else:
        choice = input("Copy or symlink? (c/s) [c]: ").strip().lower()
        if choice == 's':
            method = "symlink"

    # Perform switch
    success = switch_model(selected, dest_backend, method)
    if success:
        rprint("\n[bold green]✓ Model switched successfully![/bold green]")
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()