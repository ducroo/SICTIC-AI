import pytest
from skills.dataset_chat.dataset_chat import dataset_chat, dataset_chat_json

@pytest.mark.asyncio
async def test_dataset_chat_basic(mocker):
    """
    Tests that dataset_chat correctly parses queries, retrieves chunks,
    and returns a response from llm_chat.
    """
    # Mock dataset_search
    from lib.datasets.models import Chunk
    mock_search = mocker.patch("skills.dataset_chat.dataset_chat.dataset_search")
    
    # Since dataset_search is an async function, we must mock it to return a coroutine
    async def mock_search_coro(*args, **kwargs):
        c = Chunk(chunk_id="1", document_name="test_doc.pdf", page_number=1, last_modified=0.0, text="This is a dummy chunk.", score=1.0)
        return [c]
    mock_search.side_effect = mock_search_coro

    # Mock llm_chat
    mock_llm = mocker.patch(
        "skills.dataset_chat.dataset_chat.generate_markdown"
    )
    async def mock_llm_coro(*args, **kwargs):
        return "This is the LLM response."
    mock_llm.side_effect = mock_llm_coro

    # Execute
    output = await dataset_chat(
        "test_dataset",
        "What is testing?",
        "Query: What is testing?",
    )

    # Assert
    assert output == "This is the LLM response."
    mock_search.assert_called_once_with(
        "test_dataset",
        "What is testing?",
        max_chunks=25,
        raise_on_error=True,
    )
    mock_llm.assert_called_once()

@pytest.mark.asyncio
async def test_dataset_chat_separates_search_queries_from_prompt(mocker):
    from lib.datasets.models import Chunk

    mock_search = mocker.patch("skills.dataset_chat.dataset_chat.dataset_search")
    mock_search.return_value = [
        Chunk(
            chunk_id="1",
            document_name="test_doc.pdf",
            page_number=1,
            last_modified=0.0,
            text="This is a dummy chunk.",
            score=1.0,
        )
    ]
    mock_llm = mocker.patch(
        "skills.dataset_chat.dataset_chat.generate_markdown",
        return_value="This is the LLM response.",
    )
    queries = ["What is testing?", "testing validation quality"]

    output = await dataset_chat(
        "test_dataset",
        queries,
        "Question: Why does testing matter?",
    )

    assert output == "This is the LLM response."
    mock_search.assert_awaited_once_with(
        "test_dataset",
        queries,
        max_chunks=25,
        raise_on_error=True,
    )
    prompt = mock_llm.call_args.args[0]
    assert "Question: Why does testing matter?" in prompt
    assert "testing validation quality" not in prompt


@pytest.mark.asyncio
async def test_dataset_chat_json_forwards_schema(mocker):
    from lib.datasets.models import Chunk

    mocker.patch(
        "skills.dataset_chat.dataset_chat.dataset_search",
        return_value=[
            Chunk(
                chunk_id="1",
                document_name="test.md",
                page_number=1,
                last_modified=0.0,
                text="Evidence.",
                score=1.0,
            )
        ],
    )
    mock_llm = mocker.patch(
        "skills.dataset_chat.dataset_chat.generate_json",
        return_value={"answer": "yes"},
    )
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }

    result = await dataset_chat_json(
        "test",
        "query",
        "prompt",
        schema,
    )

    assert result == {"answer": "yes"}
    assert mock_llm.await_args.args[1] is schema


@pytest.mark.asyncio
async def test_dataset_chat_separates_cacheable_prefix_from_dynamic_context(mocker):
    from lib.datasets.models import Chunk

    mocker.patch(
        "skills.dataset_chat.dataset_chat.dataset_search",
        return_value=[
            Chunk(
                chunk_id="1",
                document_name="evidence.md",
                page_number=1,
                last_modified=0.0,
                text="Question-specific evidence.",
                score=1.0,
            )
        ],
    )
    mock_llm = mocker.patch(
        "skills.dataset_chat.dataset_chat.generate_markdown",
        return_value="ok",
    )

    await dataset_chat(
        "test",
        "dynamic query",
        "CURRENT CHECK: dynamic question",
        cacheable_prompt_prefix="SHARED AUDIT DOCUMENTS AND SCHEMA",
    )

    call = mock_llm.await_args.kwargs
    assert call["cacheable_prompt_prefix"].startswith(
        "Use ONLY the context below"
    )
    assert "SHARED AUDIT DOCUMENTS AND SCHEMA" in call[
        "cacheable_prompt_prefix"
    ]
    assert "dynamic question" not in call["cacheable_prompt_prefix"]
    assert "CURRENT CHECK: dynamic question" in mock_llm.await_args.args[0]
    assert "Question-specific evidence." in mock_llm.await_args.args[0]


@pytest.mark.asyncio
async def test_dataset_chat_refuses_empty_context(mocker):
    mock_search = mocker.patch("skills.dataset_chat.dataset_chat.dataset_search")
    mock_search.return_value = []
    mock_llm = mocker.patch(
        "skills.dataset_chat.dataset_chat.generate_markdown"
    )
    mock_config = mocker.patch(
        "skills.dataset_chat.dataset_chat.load_repository_config"
    )
    mock_config.return_value = {"fallback_trigger": "INSUFFICIENT_CONTEXT"}

    output = await dataset_chat(
        "test_dataset",
        "What is testing?",
        "Query: What is testing?",
    )

    assert output == "INSUFFICIENT_CONTEXT"
    mock_llm.assert_not_called()


@pytest.mark.asyncio
async def test_dataset_chat_budgets_context_without_front_truncation(mocker, monkeypatch):
    from lib.datasets.models import Chunk

    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH_MAX", "2048")
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
    mock_config = mocker.patch(
        "skills.dataset_chat.dataset_chat.load_repository_config"
    )
    mock_config.return_value = {"fallback_trigger": "INSUFFICIENT_CONTEXT"}
    mock_llm = mocker.patch(
        "skills.dataset_chat.dataset_chat.generate_markdown",
        return_value="grounded",
    )

    output = await dataset_chat(
        "avientus",
        "Profile Avientus",
        "Query: Profile Avientus\n\nInstructions: Use only context.",
    )

    assert output == "grounded"
    prompt = mock_llm.call_args.args[0]
    assert prompt.startswith("Use ONLY the context below")
    assert "Query: Profile Avientus" in prompt
    assert "Context from avientus:" in prompt
    assert len(prompt) < 2048 * 3
    assert "doc-0.md" in prompt
    assert "doc-9.md" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prefix", "allow_empty", "generates"),
    [("Profile evidence: cv.pdf — page 1.", True, True),
     ("Profile evidence: cv.pdf — page 1.", False, False),
     (None, True, False)],
)
async def test_json_empty_retrieval_requires_explicit_shared_evidence_mode(
    mocker, prefix, allow_empty, generates,
):
    mocker.patch("skills.dataset_chat.dataset_chat.dataset_search", return_value=[])
    generate = mocker.patch("skills.dataset_chat.dataset_chat.generate_json", return_value={"answer": "documented"})
    result = await dataset_chat_json(
        "test", "founder experience", "Assess experience", {"type": "object"},
        cacheable_prompt_prefix=prefix,
        allow_empty_retrieval=allow_empty,
    )
    assert generate.await_count == int(generates)
    if generates:
        assert result == {"answer": "documented"}
        assert prefix in generate.await_args.kwargs["cacheable_prompt_prefix"]
        assert "No question-specific evidence was retrieved" not in generate.await_args.args[0]
    else:
        assert result is None
