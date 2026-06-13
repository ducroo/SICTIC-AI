import os
import json
import pytest
import asyncio
from lib.services_gateway import ServicesGateway, Priority, GATEWAY_STATE_FILE

@pytest.fixture
def clean_gateway():
    # Ensure a fresh state file
    if os.path.exists(GATEWAY_STATE_FILE):
        os.remove(GATEWAY_STATE_FILE)
    
    gateway = ServicesGateway()
    # Reset internal limits for testing
    gateway.OLLAMA_NUM_PARALLEL = 2
    return gateway

def read_state():
    if not os.path.exists(GATEWAY_STATE_FILE):
        return {}
    with open(GATEWAY_STATE_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

@pytest.mark.asyncio
async def test_gateway_initialization(clean_gateway):
    """Ensure the gateway starts completely idle."""
    state = read_state()
    assert state.get("active_docling", []) == []
    assert state.get("active_embeds", []) == []
    assert state.get("active_llms", []) == []

@pytest.mark.asyncio
async def test_gateway_mode_switching(clean_gateway, mocker):
    """
    Test that the gateway correctly enforces mode exclusivity (Traffic Cop logic)
    using the new IPC file locking. If an LLM job is running, embedding jobs must wait.
    """
    # Mock litellm to simulate work
    async def mock_llm_completion(**kwargs):
        await asyncio.sleep(0.5)
        return "Mocked LLM"
        
    async def mock_embedding(**kwargs):
        await asyncio.sleep(0.1)
        return "Mocked Embedding"
        
    mocker.patch("litellm.acompletion", side_effect=mock_llm_completion)
    mocker.patch("litellm.aembedding", side_effect=mock_embedding)
    
    # 1. Dispatch an LLM request
    llm_task = asyncio.create_task(clean_gateway.request_completion({}))
    
    # Wait slightly to ensure it acquired the lock
    await asyncio.sleep(0.1)
    state = read_state()
    assert len(state.get("active_llms", [])) == 1
    assert len(state.get("active_embeds", [])) == 0
    
    # 2. Dispatch an Embedding request while the LLM is running
    embed_task = asyncio.create_task(clean_gateway.request_embedding({}))
    
    # Give it a moment to try acquiring
    await asyncio.sleep(0.1)
    
    # Assert that the embedding task has NOT started because LLM is running
    state = read_state()
    assert len(state.get("active_llms", [])) == 1
    assert len(state.get("active_embeds", [])) == 0
    
    # 3. Wait for the LLM task to finish
    await llm_task
    
    # Now the embedding task should be able to finish
    await embed_task
    
    # System should gracefully return to IDLE
    state = read_state()
    assert len(state.get("active_llms", [])) == 0
    assert len(state.get("active_embeds", [])) == 0

@pytest.mark.asyncio
async def test_gateway_concurrency_limits(clean_gateway, mocker):
    """
    Test that the gateway strictly limits the number of concurrent jobs allowed
    based on the state file.
    """
    async def mock_slow_embedding(**kwargs):
        # We check the state *while* the tasks are running inside litellm
        state = read_state()
        assert len(state.get("active_embeds", [])) <= clean_gateway.OLLAMA_NUM_PARALLEL
        await asyncio.sleep(0.2)
        return "Mock"
    
    mocker.patch("litellm.aembedding", side_effect=mock_slow_embedding)
    
    # Dispatch 4 embedding requests (Limit is mocked to 2)
    tasks = []
    for _ in range(4):
        tasks.append(asyncio.create_task(clean_gateway.request_embedding({})))
        
    await asyncio.gather(*tasks)
    
    state = read_state()
    assert len(state.get("active_embeds", [])) == 0
