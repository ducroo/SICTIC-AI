import os
import typer
from dotenv import load_dotenv
from skills.utils.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="Environment variable utility.")

# Auto-load dotenv when module is imported
dotenv_path = os.path.join(os.path.expanduser("~"), ".openclaw", "workspace-sictic-ai", ".env")
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path, override=True)

def get_env_var(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"CRITICAL ERROR: Missing required environment variable '{name}'.")
    return value

@app.command()
def get(name: str):
    """CLI wrapper to fetch environment variables."""
    try:
        print(get_env_var(name))
    except ValueError as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
