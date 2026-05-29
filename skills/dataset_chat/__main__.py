import typer
from typing import Optional, List
from skills.dataset_chat.dataset_chat import dataset_chat
from skills.dataset_chat.dataset_search import dataset_search
from skills.dataset_chat.dataset_delete import dataset_delete
from skills.dataset_chat.core.ingestion import sync_datasets
from lib.adapters.qdrant import QdrantAdapter
from lib.logger import get_logger

logger = get_logger(__name__)

app = typer.Typer(help="High-precision Dataset Chat and RAG Engine.")

@app.command("search")
def search_cmd(
    dataset_name: str = typer.Argument(..., help="Name of the dataset/collection to search."),
    query: str = typer.Argument("", help="The query/question to search for.")
):
    try:
        import asyncio
        chunks = asyncio.run(dataset_search(dataset_name, [query]))
        for c in chunks:
            print(f"[Source: {c.document_name}, Page: {c.page_number}]\n{c.text}\n")
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

@app.command("chat")
def chat_cmd(
    dataset_name: str = typer.Argument(..., help="Name of the dataset/collection to chat with."),
    questions: str = typer.Argument(..., help="The query/question to ask."),
    llm_instructions: Optional[str] = typer.Argument(None, help="Optional formatting/anti-hallucination instructions.")
):
    try:
        import asyncio
        response = asyncio.run(dataset_chat(dataset_name, questions, llm_instructions))
        if response:
            print(response)
    except typer.Exit:
        raise
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

@app.command("sync")
def sync_cmd(
    dataset_names: List[str] = typer.Argument(..., help="Names of the datasets/collections to sync. Can pass multiple separated by spaces.")
):
    try:
        import asyncio
        asyncio.run(sync_datasets(dataset_names, raise_on_error=True))
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

@app.command("delete")
def delete_cmd(
    dataset: Optional[str] = typer.Option(None, "--dataset", "-d", help="Name of the dataset/collection to delete."),
    embeddings: Optional[str] = typer.Option(None, "--embeddings", "-e", help="Target embedding model to delete.")
):
    try:
        dataset_delete(dataset, embeddings)
    except Exception as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
