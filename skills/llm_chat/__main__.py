import typer
from rich.console import Console
from rich.markdown import Markdown
from skills.llm_chat.llm_chat import llm_chat
from lib.logger import get_logger

logger = get_logger(__name__)


console = Console()
app = typer.Typer(help="CLI tool to interact with LLMs using LiteLLM.")

@app.command()
def main(
    prompt: str = typer.Argument(..., help="The prompt/message you want to send to the LLM.")
):
    try:
        content = llm_chat(prompt)
        if content:
            console.print("\n")
            console.print(Markdown(content))
            console.print("\n")
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
