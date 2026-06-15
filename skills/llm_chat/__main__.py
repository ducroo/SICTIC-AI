import typer
from rich.console import Console
from rich.markdown import Markdown

from lib.cli import run_command
from lib.logger import get_logger
from skills.llm_chat.llm_chat import llm_chat

logger = get_logger(__name__)


console = Console()
app = typer.Typer(help="CLI tool to interact with LLMs using LiteLLM.")

@app.command()
def main(
    prompt: str = typer.Argument(..., help="The prompt/message you want to send to the LLM.")
):
    content = run_command(
        lambda: llm_chat(prompt),
        logger=logger,
        error_prefix="Execution failed",
    )
    if content:
        console.print("\n")
        console.print(Markdown(content))
        console.print("\n")

if __name__ == "__main__":
    app()
