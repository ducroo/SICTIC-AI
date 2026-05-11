import typer
from typing import List, Optional
from skills.startup_profile.startup_profile import startup_profile
from skills.utils.logger import get_logger

logger = get_logger(__name__)



app = typer.Typer(help="Generates a neutral, objective 5-point diagnostic of a startup.")

@app.command()
def profile_startup(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup"),
    files: Optional[List[str]] = typer.Option(None, "--files", "-f", help="Optional list of PDF/document files")
):
    import asyncio
    try:
        logger.info(f"Starting profile generation for startup: {startup}")
        profile_output, output_file = asyncio.run(startup_profile(startup, files))
        
        print("\n--- Profile Output ---\n")
        print(profile_output)
        print("\n----------------------\n")
        logger.info(f"Successfully saved profile to {output_file}")
        
    except ValueError as ve:
        print(f"{startup} is not found , {ve}")
        raise typer.Exit(code=0)
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
