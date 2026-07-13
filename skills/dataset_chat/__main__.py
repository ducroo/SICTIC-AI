import typer
from typing import Optional, List

from lib.cli import run_command
from lib.logger import get_logger
from lib.datasets.ingestion import sync_datasets
from skills.dataset_chat.dataset_chat import dataset_chat
from lib.datasets.search import dataset_search

logger = get_logger(__name__)

app = typer.Typer(help="High-precision Dataset Chat and RAG Engine.")

@app.command("search")
def search_cmd(
    dataset_name: str = typer.Argument(..., help="Name of the dataset/collection to search."),
    query: str = typer.Argument("", help="The query/question to search for.")
):
    chunks = run_command(
        lambda: dataset_search(dataset_name, query),
        logger=logger,
    )
    for chunk in chunks:
        source_label = (
            f"[Source: {chunk.document_name}]"
            if chunk.page_number == "n/a"
            else f"[Source: {chunk.document_name}, Page: {chunk.page_number}]"
        )
        typer.echo(
            f"{source_label}\n"
            f"{chunk.text}\n"
        )

@app.command("chat")
def chat_cmd(
    dataset_name: str = typer.Argument(..., help="Name of the dataset/collection to chat with."),
    questions: str = typer.Argument(..., help="The query/question to ask."),
    llm_instructions: Optional[str] = typer.Argument(None, help="Optional formatting/anti-hallucination instructions.")
):
    response = run_command(
        lambda: dataset_chat(dataset_name, questions, llm_instructions),
        logger=logger,
    )
    if response:
        typer.echo(response)

@app.command("sync")
def sync_cmd(
    dataset_names: List[str] = typer.Argument(..., help="Names of the datasets/collections to sync. Can pass multiple separated by spaces."),
    force: bool = typer.Option(False, "--force", help="Bypass the short in-process sync cache.")
):
    run_command(
        lambda: sync_datasets(dataset_names, raise_on_error=True, force=force),
        logger=logger,
    )

if __name__ == "__main__":
    app()
