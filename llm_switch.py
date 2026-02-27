#!/usr/bin/env python3
"""
LLM Model Switcher – Zero‑Brain Edition

Automatically finds models from common LLM backends (llama.cpp, LM Studio, Jan.ai, etc.)
anywhere on your system, lets you pick one and a destination backend, then copies or symlinks
it to the right place. If nothing is found in usual spots, it offers to do a deep scan of your
home folder. Also reads your local‑llm config and highlights the active model with a ⭐ star.
"""

import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

# Optional rich UI (beautiful tables, progress bars)
try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
    from rich import print as rprint
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

# Optional questionary (fancy interactive menus)
try:
    import questionary
    HAS_QUESTIONARY = True
except ImportError:
    HAS_QUESTIONARY = False

# ==================== CONFIG PARSING ====================
def get_active_model_name() -> Optional[str]:
    """Reads ~/.config/local-llm/selected_model.conf and returns MODEL_NAME."""
    config_path = Path.home() / ".config" / "local-llm" / "selected_model.conf"
    if not config_path.exists():
        return None
    try:
        for line in config_path.read_text().splitlines():
            if line.startswith("MODEL_NAME="):
                parts = line.split('"')
                if len(parts) >= 2:
                    return parts[1]
    except Exception:
        pass
    return None

# ==================== ULTRA‑BROAD PATH SCANNER ====================
def get_common_model_dirs() -> Dict[str, List[Path]]:
    """
    Returns a dict of backend name -> list of directories to scan.
    Covers all common places on Windows and Linux, including your custom
    ~/.local/share/llm-models.
    """
    home = Path.home()
    paths = {}

    # ----- llama.cpp -----
    llama_paths = [
        home / "models",
        home / "llama.cpp" / "models",
        home / "llama" / "models",
        home / ".llama" / "models",
        Path.cwd() / "models",
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
    paths["llama.cpp"] = list(dict.fromkeys(llama_paths))

    # ----- LM Studio -----
    lmstudio_paths = []
    if platform.system() == "Windows":
        user_profile = Path(os.environ.get("USERPROFILE", ""))
        if user_profile:
            lmstudio_paths.append(user_profile / ".lmstudio" / "models")
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        if localappdata.exists():
            lmstudio_paths.append(localappdata / "LM Studio" / "models")
    else:
        lmstudio_paths.append(home / ".lmstudio" / "models")
        lmstudio_paths.append(home / "Library/Application Support/LM Studio/models")  # macOS
    paths["LM Studio"] = lmstudio_paths

    # ----- Jan.ai -----
    jan_paths = []
    if platform.system() == "Windows":
        user_profile = Path(os.environ.get("USERPROFILE", ""))
        if user_profile:
            jan_paths.append(user_profile / "jan" / "models")
        localappdata = Path(os.environ.get("LOCALAPPDATA", ""))
        if localappdata.exists():
            jan_paths.append(localappdata / "jan" / "models")
    else:
        jan_paths.append(home / "jan" / "models")
        jan_paths.append(home / ".jan" / "models")
    paths["Jan.ai"] = jan_paths

    # ----- Oobabooga (Text Generation WebUI) -----
    ooba_paths = [
        home / "oobabooga" / "models",
        home / "text-generation-webui" / "models",
    ]
    if platform.system() == "Windows":
        user_profile = Path(os.environ.get("USERPROFILE", ""))
        if user_profile:
            ooba_paths.append(user_profile / "oobabooga" / "models")
    paths["Oobabooga"] = ooba_paths

    # ----- General / catch‑all (including your custom path) -----
    general_paths = [
        home / "Downloads",
        home / "Documents" / "models",
        home / ".local/share/llm-models",      # your custom directory
        Path("/models"),
    ]
    if platform.system() == "Windows":
        general_paths.append(Path("C:/models"))
    paths["Other locations"] = general_paths

    return paths

# Build the BACKENDS dict with file extensions
COMMON_BACKENDS = {}
for name, dirs in get_common_model_dirs().items():
    COMMON_BACKENDS[name] = {
        "paths": dirs,
        "extensions": [".gguf", ".bin", ".pt", ".pth", ".safetensors"],
    }

# We'll also optionally add a "Deep scan" backend later if user chooses.

# ==================== DEEP SCAN ====================
def deep_scan_models() -> List[Dict[str, Any]]:
    """
    Recursively scan the user's home directory for model files.
    Warning: this can be slow on large disks.
    """
    home = Path.home()
    models = []
    extensions = [".gguf", ".bin", ".pt", ".pth", ".safetensors"]
    console = Console() if HAS_RICH else None

    if console:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=False,
        ) as progress:
            task = progress.add_task("Deep scanning your home folder...", total=None)
            for ext in extensions:
                for model_path in home.rglob(f"*{ext}"):
                    if model_path.is_file():
                        stat = model_path.stat()
                        models.append({
                            "name": model_path.name,
                            "path": str(model_path.absolute()),
                            "backend": "Deep scan",
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                        })
            progress.update(task, completed=True)
    else:
        print("Deep scanning your home folder... (this may take a while)")
        for ext in extensions:
            for model_path in home.rglob(f"*{ext}"):
                if model_path.is_file():
                    stat = model_path.stat()
                    models.append({
                        "name": model_path.name,
                        "path": str(model_path.absolute()),
                        "backend": "Deep scan",
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    })
    return models

# ==================== MODEL DISCOVERY (COMMON PATHS) ====================
def discover_models_common() -> List[Dict[str, Any]]:
    """Walk through common directories and collect model files."""
    models = []
    console = Console() if HAS_RICH else None

    if console:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task("Scanning common places for models...", total=None)
            for backend_name, config in COMMON_BACKENDS.items():
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
        print("Scanning common places for models...")
        for backend_name, config in COMMON_BACKENDS.items():
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

# ==================== HELP WHEN NOTHING FOUND ====================
def ask_for_deep_scan() -> bool:
    """Offer to do a deep scan if initial scan found nothing."""
    rprint("\n[bold yellow]No models found in common places.[/bold yellow]")
    if HAS_QUESTIONARY:
        return questionary.confirm("Do you want to do a deep scan of your entire home folder? (may be slow)").ask()
    else:
        resp = input("Do you want to do a deep scan of your entire home folder? (y/N): ").strip().lower()
        return resp == 'y'

def ask_for_custom_paths() -> bool:
    """Let user manually add a folder."""
    rprint("\n[bold yellow]No models found even after deep scan.[/bold yellow]")

    if HAS_QUESTIONARY:
        while True:
            path_str = questionary.path(
                "Enter the full path to a folder containing your models (or leave blank to finish):",
                only_directories=True
            ).ask()
            if not path_str:
                break
            path = Path(path_str).expanduser().resolve()
            if path.exists() and path.is_dir():
                if "User added" not in COMMON_BACKENDS:
                    COMMON_BACKENDS["User added"] = {"paths": [], "extensions": [".gguf", ".bin", ".pt", ".pth", ".safetensors"]}
                COMMON_BACKENDS["User added"]["paths"].append(path)
                rprint(f"[green]Added {path}[/green]")
            else:
                rprint("[red]That folder does not exist. Try again.[/red]")
        return True
    else:
        print("Enter paths one per line (empty line to finish):")
        while True:
            path_str = input("Path: ").strip()
            if not path_str:
                break
            path = Path(path_str).expanduser().resolve()
            if path.exists() and path.is_dir():
                if "User added" not in COMMON_BACKENDS:
                    COMMON_BACKENDS["User added"] = {"paths": [], "extensions": [".gguf", ".bin", ".pt", ".pth", ".safetensors"]}
                COMMON_BACKENDS["User added"]["paths"].append(path)
                print(f"Added {path}")
            else:
                print("Invalid path, try again.")
        return True

# ==================== SELECTION INTERFACE ====================
def show_models_table(models: List[Dict[str, Any]], active_name: Optional[str] = None) -> None:
    """Display a rich table of discovered models, marking the active one with a star."""
    if not HAS_RICH:
        return
    console = Console()
    table = Table(title="Discovered Models", show_lines=True)
    table.add_column(" ", style="bold yellow", width=2)  # star column
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("Backend", style="magenta")
    table.add_column("Model Name", style="green")
    table.add_column("Size", justify="right", style="yellow")

    for idx, m in enumerate(models, 1):
        star = "⭐" if active_name and m["name"] == active_name else ""
        size_mb = m["size"] / (1024 * 1024)
        table.add_row(
            star,
            str(idx),
            m["backend"],
            m["name"],
            f"{size_mb:.1f} MB"
        )
    console.print(table)

def select_model_interactive(models: List[Dict[str, Any]], active_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Let user pick a model, with the active one highlighted."""
    if not models:
        return None

    if HAS_RICH:
        show_models_table(models, active_name)

    if HAS_QUESTIONARY:
        choices = []
        for m in models:
            size_mb = m["size"] / (1024 * 1024)
            prefix = "⭐ " if active_name and m["name"] == active_name else "   "
            label = f"{prefix}[{m['backend']}] {m['name']} ({size_mb:.1f} MB)"
            choices.append(questionary.Choice(title=label, value=m))
        answer = questionary.select(
            "Select a model:",
            choices=choices,
            use_shortcuts=True,
            qmark="🦙",
        ).ask()
        return answer
    else:
        # Fallback with simple numbered list
        print("\nAvailable models:")
        for i, m in enumerate(models, 1):
            size_mb = m["size"] / (1024 * 1024)
            star = " ⭐" if active_name and m["name"] == active_name else ""
            print(f"{i:3}. [{m['backend']}] {m['name']} ({size_mb:.1f} MB){star}")
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
    # Combine COMMON_BACKENDS with any user-added backends
    all_backends = COMMON_BACKENDS.copy()
    dest_backends = [name for name in all_backends if name != source_backend and all_backends[name]["paths"]]
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

# ==================== SWITCHING LOGIC ====================
def switch_model(model: Dict[str, Any], dest_backend: str, method: str = "copy") -> bool:
    """Copy or symlink model to destination backend's first path."""
    src_path = Path(model["path"])
    dest_dir = COMMON_BACKENDS[dest_backend]["paths"][0]
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
        try:
            if dest_path.is_symlink() or dest_path.is_file():
                dest_path.unlink()
            elif dest_path.is_dir():
                shutil.rmtree(dest_path)
        except Exception as e:
            rprint(f"[red]Could not remove existing file: {e}[/red]")
            return False

    # Perform switch
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
        else:
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

# ==================== MAIN ====================
def main():
    # Minimal intro
    if HAS_RICH:
        console = Console()
        console.rule("[bold blue]LLM Model Switcher (Zero‑Brain)[/bold blue]")
        console.print()

    # Get active model from config
    active_name = get_active_model_name()
    if active_name and HAS_RICH:
        console.print(f"Active model from config: [bold yellow]⭐ {active_name}[/bold yellow]")

    # Discover models in common places
    models = discover_models_common()

    # If none, offer deep scan
    if not models:
        if ask_for_deep_scan():
            models = deep_scan_models()
        if not models:
            # Still none? ask for manual folder
            if ask_for_custom_paths():
                models = discover_models_common()  # rescan with user-added paths
            if not models:
                rprint("[red]No models found. Exiting.[/red]")
                sys.exit(1)

    # Select source model
    selected = select_model_interactive(models, active_name)
    if selected is None:
        rprint("[yellow]No model selected. Exiting.[/yellow]")
        sys.exit(0)

    # Select destination backend
    dest_backend = select_destination_backend(selected["backend"])
    if dest_backend is None:
        rprint("[yellow]No destination selected. Exiting.[/yellow]")
        sys.exit(0)

    # Choose copy or symlink
    method = "copy"
    if HAS_QUESTIONARY:
        method = questionary.select(
            "How to switch?",
            choices=[
                questionary.Choice("Copy (safe, uses disk space)", value="copy"),
                questionary.Choice("Symlink (saves space, may need admin)", value="symlink"),
            ],
            default="copy"
        ).ask()
        if method is None:
            method = "copy"
    else:
        choice = input("Copy or symlink? (c/s) [c]: ").strip().lower()
        if choice == 's':
            method = "symlink"

    # Do it
    success = switch_model(selected, dest_backend, method)
    if success:
        rprint("\n[bold green]✓ Model switched successfully![/bold green]")
        rprint(f"Now you can use it in {dest_backend}.")
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()