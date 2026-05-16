#!/usr/bin/env python3
import typer
from skills.config_load.config_load import config_load, get_base_paths
from lib.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="Load JSON configuration from Google Drive.")

@app.command()
def load():
    try:
        try:
            from rich.console import Console
            console = Console()
        except ImportError:
            console = None

        if console:
            with console.status("[bold blue]Loading configurations...[/bold blue]"):
                config_data = config_load()
        else:
            config_data = config_load()

        skill_count = len(config_data) if isinstance(config_data, dict) else 0
        
        if console:
            console.print(f"[bold green]Successfully pulled configuration for {skill_count} skills.[/bold green]")
        else:
            logger.info(f"Successfully pulled configuration for {skill_count} skills.")
            
        _, _, _, cache_file = get_base_paths()
        print(f"RESULT_PATH: {cache_file}")
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
