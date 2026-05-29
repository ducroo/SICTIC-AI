import pytest
from skills.dataset_chat.dataset_chat import dataset_chat

@pytest.mark.asyncio
async def test_dataset_chat_basic(mocker):
    """
    Tests that dataset_chat correctly parses queries, retrieves chunks,
    and returns a response from llm_chat.
    """
    # Mock dataset_search
    from skills.dataset_chat.core.models import Chunk
    mock_search = mocker.patch("skills.dataset_chat.dataset_chat.dataset_search")
    
    # Since dataset_search is an async function, we must mock it to return a coroutine
    async def mock_search_coro(*args, **kwargs):
        c = Chunk(chunk_id="1", document_name="test_doc.pdf", page_number=1, last_modified=0.0, text="This is a dummy chunk.", score=1.0)
        return [c]
    mock_search.side_effect = mock_search_coro

    # Mock llm_chat
    mock_llm = mocker.patch("skills.dataset_chat.dataset_chat.llm_chat")
    async def mock_llm_coro(*args, **kwargs):
        return "This is the LLM response."
    mock_llm.side_effect = mock_llm_coro

    # Execute
    output = await dataset_chat("test_dataset", "What is testing?")

    # Assert
    assert output == "This is the LLM response."
    mock_search.assert_called_once_with("test_dataset", "What is testing?", max_chunks=25)
    mock_llm.assert_called_once()

@pytest.mark.asyncio
async def test_dataset_chat_fallback(mocker):
    """
    Tests that dataset_chat generates multi-queries and retries
    if the first pass triggers the fallback string.
    """
    # Mock dataset_search
    from skills.dataset_chat.core.models import Chunk
    mock_search = mocker.patch("skills.dataset_chat.dataset_chat.dataset_search")
    async def mock_search_coro(*args, **kwargs):
        return [Chunk(chunk_id="1", document_name="test_doc.pdf", page_number=1, last_modified=0.0, text="This is a dummy chunk.", score=1.0)]
    mock_search.side_effect = mock_search_coro

    # Mock llm_chat to trigger fallback on first call, success on second
    mock_llm = mocker.patch("skills.dataset_chat.dataset_chat.llm_chat")
    mock_llm.side_effect = ["INSUFFICIENT_CONTEXT", "This is the retry response."]

    # Mock config_load
    mock_config = mocker.patch("skills.dataset_chat.dataset_chat.config_load")
    mock_config.return_value = {
        "dataset_chat": {
            "fallback_trigger": "INSUFFICIENT_CONTEXT"
        }
    }

    # Mock generate_multi_queries
    mock_multi = mocker.patch("skills.dataset_chat.dataset_chat.generate_multi_queries")
    mock_multi.return_value = ["What is the definition of testing?"]

    # Execute
    output = await dataset_chat("test_dataset", "What is testing?")

    # Assert
    assert output == "This is the retry response."
    assert mock_search.call_count == 2
    assert mock_llm.call_count == 2
    mock_multi.assert_called_once_with("What is testing?")


@pytest.mark.asyncio
async def test_dataset_chat_refuses_empty_context(mocker):
    mock_search = mocker.patch("skills.dataset_chat.dataset_chat.dataset_search")
    mock_search.return_value = []
    mock_llm = mocker.patch("skills.dataset_chat.dataset_chat.llm_chat")
    mock_config = mocker.patch("skills.dataset_chat.dataset_chat.config_load")
    mock_config.return_value = {
        "dataset_chat": {
            "fallback_trigger": "INSUFFICIENT_CONTEXT"
        }
    }

    output = await dataset_chat("test_dataset", "What is testing?")

    assert output == "INSUFFICIENT_CONTEXT"
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_dataset_chat_budgets_context_without_front_truncation(mocker, monkeypatch):
    from skills.dataset_chat.core.models import Chunk

    monkeypatch.setenv("OLLAMA_NUM_CTX_MAX", "2048")
    chunks = [
        Chunk(
            chunk_id=str(i),
            document_name=f"doc-{i}.md",
            page_number=1,
            last_modified=0.0,
            text=("Relevant Avientus evidence. " * 80),
            score=1.0,
        )
        for i in range(10)
    ]
    mocker.patch("skills.dataset_chat.dataset_chat.dataset_search", return_value=chunks)
    mock_config = mocker.patch("skills.dataset_chat.dataset_chat.config_load")
    mock_config.return_value = {
        "dataset_chat": {
            "fallback_trigger": "INSUFFICIENT_CONTEXT"
        }
    }
    mock_llm = mocker.patch("skills.dataset_chat.dataset_chat.llm_chat", return_value="grounded")

    output = await dataset_chat("avientus", "Profile Avientus", "Use only context.")

    assert output == "grounded"
    prompt = mock_llm.call_args.kwargs["prompt"]
    assert prompt.startswith("Use ONLY the context below")
    assert "Query: Profile Avientus" in prompt
    assert "Context from avientus:" in prompt
    assert len(prompt) < 2048 * 3
    assert "doc-0.md" in prompt
    assert "doc-9.md" not in prompt
