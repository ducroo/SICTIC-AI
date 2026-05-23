import pytest
from skills.dataset_chat.dataset_chat import dataset_chat

@pytest.mark.asyncio
async def test_dataset_chat_basic(mocker):
    """
    Tests that dataset_chat correctly parses queries, retrieves chunks, 
    and returns a response from llm_chat.
    """
    # Mock dataset_search
    mock_search = mocker.patch("skills.dataset_chat.dataset_chat.dataset_search")
    class MockChunk:
        def __init__(self):
            self.document_name = "test_doc.pdf"
            self.page_number = 1
            self.text = "This is a dummy chunk."
    
    # Since dataset_search is an async function, we must mock it to return a coroutine
    async def mock_search_coro(*args, **kwargs):
        return [MockChunk()]
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
    mock_search.assert_called_once_with("test_dataset", "What is testing?", max_chunks=25, return_full_docs=False)
    mock_llm.assert_called_once()

@pytest.mark.asyncio
async def test_dataset_chat_fallback(mocker):
    """
    Tests that dataset_chat generates multi-queries and retries
    if the first pass triggers the fallback string.
    """
    # Mock dataset_search
    mock_search = mocker.patch("skills.dataset_chat.dataset_chat.dataset_search")
    async def mock_search_coro(*args, **kwargs):
        return []
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
