import os
import typer
from dotenv import load_dotenv
from lib.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="Environment variable utility.")

# Auto-load dotenv when module is imported.
# Resolve .env relative to this file (repo_root/.env) so it works regardless of CWD
# or host (the same repo runs from different absolute paths on different machines).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(_REPO_ROOT, ".env")
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
