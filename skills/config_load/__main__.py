#!/usr/bin/env python3
import typer

from lib.cli import run_command
from lib.logger import get_logger
from skills.config_load.config_load import _local_cache_paths, config_load

logger = get_logger(__name__)

app = typer.Typer(help="Load JSON configuration from the local repository.")

@app.command()
def load():
    def load_config():
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

        return _local_cache_paths()[1]

    cache_file = run_command(
        load_config,
        logger=logger,
        error_prefix="Execution failed",
    )
    typer.echo(f"RESULT_PATH: {cache_file}")

if __name__ == "__main__":
    app()
