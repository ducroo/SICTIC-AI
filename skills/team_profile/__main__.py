import typer
from typing import List, Optional
from skills.team_profile.team_profile import team_profile
from lib.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="Performs deep-dive due diligence on a startup's leadership.")

@app.command()
def profile_team(
    startup: str = typer.Option(..., "--startup", "-s", help="Name of the startup"),
    files: Optional[List[str]] = typer.Option(None, "--files", "-f", help="Optional list of PDF/document files")
):
    try:
        logger.info(f"Starting team profile generation for startup: {startup}")
        profile_output, output_file = team_profile(startup, files)
        
        print("\n--- Team Profile Output ---\n")
        print(profile_output)
        print("\n---------------------------\n")
        logger.info(f"Successfully saved team profile to {output_file}")
        
    except ValueError as ve:
        logger.error(f"Validation error: {ve}")
        print(f"Error: {ve}")
        raise typer.Exit(code=1)
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        print(f"Execution failed: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()