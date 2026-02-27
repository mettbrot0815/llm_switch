#!/usr/bin/env python3
"""
LLM Model Switcher – Zero‑Config Edition

Automatically finds models from common LLM backends (llama.cpp, LM Studio, Jan.ai, etc.)
on your system, lets you pick one and a destination backend, then copies or symlinks it
to the right place. No setup, no environment variables – just run and go.
"""

import os
import sys
import shutil
import platform
from pathlib import Path
from typing import List, Dict, Any, Optional

# Rich UI (fallback to basic if not installed)
try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich.prompt import Confirm, Prompt
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

# -------------------- Ultra‑Broad Path Scanner --------------------
def get_all_potential_model_dirs() -> Dict[str, List[Path]]:
    """
    Return a dictionary of backend names -> list of directories to scan.
    These are gathered from common installation patterns across Windows and Linux.
    """
    home = Path.home()
    paths = {}

    # ----- llama.cpp -----
    llama_paths = [
        home / "models",
        home / "llama.cpp" / "models",
        home / "llama" / "models",
        home / ".llama" / "models",
        Path.cwd() / "models",                 # current working directory
    ]
    if platform.system() == "Windows":
        user_profile = Path(os.environ.get("USERPROFILE", ""))
        if user_profile:
            llama_paths.extend([
                user_profile / "models",
                user_profile / "llama.cpp" / "models",
            ])
    else:  # Linux/macOS
        llama_paths.extend([
            Path("/usr/local/share/llama.cpp/models"),
            Path("/opt/llama.cpp/models"),
        ])
    paths["llama.cpp"] = list(dict.fromkeys(llama_paths))  # remove duplicates

    # ----- LM Studio -----
    lmstudio_paths = []
    if platform.system() == "Windows":
        user_profile = Path(os.environ.get("USERPROFILE", ""))
        if user_profile:
            lmstudio_paths.append(user_profile / ".lmstudio" / "models")
        # Also check the default installation location
        lmstudio_paths.append(Path(os.environ.get("LOCALAPPDATA", "")) / "LM Studio" / "models")
    else:  # macOS/Linux
        lmstudio_paths.append(home / ".lmstudio" / "models")
        lmstudio_paths.append(home / "Library" / "Application Support" / "LM Studio" / "models")  # macOS
    paths["LM Studio"] = lmstudio_paths

    # ----- Jan.ai -----
    jan_paths = []
    if platform.system() == "Windows":
        user_profile = Path(os.environ.get("USERPROFILE", ""))
        if user_profile:
            jan_paths.append(user_profile / "jan" / "models")
        jan_paths.append(Path(os.environ.get("LOCALAPPDATA", "")) / "jan" / "models")
    else:
        jan_paths.append(home / "jan" / "models")
        jan_paths.append(home / ".jan" / "models")
    paths["Jan.ai"] = jan_paths

    # ----- Ollama (models are usually in a central place, but we can try) -----
    ollama_paths = []
    if platform.system() == "Windows":
        ollama_paths.append(Path(os.environ.get("USERPROFILE", "")) / ".ollama" / "models")
    else:
        ollama_paths.append(home / ".ollama" / "models")
    paths["Ollama"] = ollama_paths

    # ----- Text Generation WebUI (oobabooga) -----
    ooba_paths = [
        home / "oobabooga" / "models",
        home / "text-generation-webui" / "models",
    ]
    if platform.system() == "Windows":
        user_profile = Path(os.environ.get("USERPROFILE", ""))
        if user_profile:
            ooba_paths.append(user_profile / "oobabooga" / "models")
    paths["Oobabooga"] = ooba_paths

    return paths

# Backend configurations with file extensions
BACKENDS = {}
for name, dirs in get_all_potential_model_dirs().items():
    BACKENDS[name] = {
        "paths": dirs,
        "extensions": [".gguf", ".bin", ".pt", ".pth", ".safetensors"],  # common model extensions
    }

# -------------------- Model Discovery --------------------
def discover_models() -> List[Dict[str, Any]]:
    """Walk through all possible directories and collect model files."""
    models = []
    console = Console() if HAS_RICH else None

    if console:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task("Scanning everywhere for models...", total=None)
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

# -------------------- Interactive Help for No Models --------------------
def ask_for_custom_paths() -> bool:
    """If no models found, ask user to add custom directories interactively."""
    rprint("\n[bold yellow]No models found in the usual places![/bold yellow]")
    rprint("Let's add a folder where your models are stored.")

    if HAS_QUESTIONARY:
        while True:
            path_str = questionary.path(
                "Enter the full path to a folder containing models (or leave blank to finish):",
                only_directories=True
            ).ask()
            if not path_str:
                break
            path = Path(path_str).expanduser().resolve()
            if path.exists() and path.is_dir():
                # Add this path to a special "User added" backend
                if "User added" not in BACKENDS:
                    BACKENDS["User added"] = {"paths": [], "extensions": [".gguf", ".bin", ".pt", ".pth", ".safetensors"]}
                BACKENDS["User added"]["paths"].append(path)
                rprint(f"[green]Added {path}[/green]")
            else:
                rprint("[red]That folder does not exist. Try again.[/red]")
        return True
    else:
        # Fallback without questionary
        print("Enter paths one per line (empty line to finish):")
        while True:
            path_str = input("Path: ").strip()
            if not path_str:
                break
            path = Path(path_str).expanduser().resolve()
            if path.exists() and path.is_dir():
                if "User added" not in BACKENDS:
                    BACKENDS["User added"] = {"paths": [], "extensions": [".gguf", ".bin", ".pt", ".pth", ".safetensors"]}
                BACKENDS["User added"]["paths"].append(path)
                print(f"Added {path}")
            else:
                print("Invalid path, try again.")
        return True

# -------------------- Display & Selection --------------------
def show_models_table(models: List[Dict[str, Any]]) -> None:
    """Display a rich table of discovered models."""
    if not HAS_RICH:
        return
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
        return None

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
    dest_backends = [name for name in BACKENDS if name != source_backend and BACKENDS[name]["paths"]]
    if not dest_backends:
        rprint("[red]No other backends with valid paths configured.[/red]")
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
    """Copy or symlink model to destination backend's first path."""
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

# -------------------- Main --------------------
def main():
    # Nice intro
    if HAS_RICH:
        console = Console()
        console.rule("[bold blue]LLM Model Switcher (Zero‑Config)[/bold blue]")
        console.print("I'll scan your computer for models – no setup needed!\n")
    else:
        print("LLM Model Switcher (Zero‑Config)")
        print("Scanning your computer for models...\n")

    # Discover models
    models = discover_models()

    # If none found, ask user to add custom paths
    if not models:
        rprint("[yellow]No models found automatically.[/yellow]")
        if HAS_QUESTIONARY:
            add_paths = questionary.confirm("Would you like to add a folder where your models are stored?").ask()
        else:
            resp = input("Would you like to add a folder where your models are stored? (y/N): ").strip().lower()
            add_paths = resp == 'y'
        if add_paths:
            ask_for_custom_paths()
            # Rescan
            models = discover_models()
        if not models:
            rprint("[red]Still no models. Exiting.[/red]")
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
                questionary.Choice("Symlink (saves space, may need admin rights)", value="symlink"),
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
        rprint(f"Now you can use it in {dest_backend}.")
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()