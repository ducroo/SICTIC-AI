import json
import sys
from types import SimpleNamespace

import pytest

from lib.batch_audit.checklist import parse_checklist
from lib.batch_audit.rendering import json_to_markdown_table
from lib.batch_audit.schema import validate_audit_document
from lib.datasets.manifest import IngestionManifest
from lib.datasets.paths import dataset_location_for_domain
from lib.datasets.source import parsed_filepath
from lib.infrastructure.configuration import load_repository_config
from lib.infrastructure.ai_text_generation.agent_model import TokenBudgetExceeded, TokenUsage
from lib.insights import InsightFile
from lib.storage import get_storage
from skills.dd_checks import agent as module
from skills.dd_checks import dd_checks as dd_checks_module
from skills.dd_checks.agent import DataRoom, DdReview, follow_up_message
from skills.dd_checks.dd_checks import checklist_chapters_and_types, dd_checks, select_checklists
from skills.dd_priorities.dd_priorities import dd_priorities

MODEL = "ollama/test_model:1b"
SETTINGS = {
    "max_read_characters": 60000,
    "max_search_results": 25,
    "search_excerpt_characters": 60,
}
DECK = (
    "<!-- sictic-page:1 -->\nAlpha Bio develops a diagnostic test.\n"
    "<!-- sictic-page:2 -->\nThe cap table lists two founders.\n"
    "<!-- sictic-page:3 -->\nRevenue in 2026 was CHF 120k.\n"
)


def make_startup(slug, documents):
    """Create a startup dossier with source files and their parsed Markdown."""
    storage = get_storage()
    location = dataset_location_for_domain(slug, "startups")
    storage.mkdir(location.raw_rel)
    for filename, parsed in documents.items():
        storage.write_text(f"{location.raw_rel}/{filename}", "source")
        storage.write_text(parsed_filepath(location.parsed_rel, filename), parsed)
    manifest = IngestionManifest(storage, location.parsed_rel)
    manifest.indexed_dataset_revision = "revision-1"
    manifest.save()
    return location


def valid_result(status="Fine", importance=5):
    return {
        "status": status,
        "importance": importance,
        "rationale": "Supported by the deck.",
        "source_documents": ["data-room/deck.pdf, page 2"],
        "proposed_next_steps_and_questions": [],
    }


@pytest.fixture
def review(mock_env, monkeypatch):
    monkeypatch.setenv("RANKED_LLMS", MODEL)
    make_startup("alpha-bio", {"data-room/deck.pdf": DECK, "data-room/notes.md": "No page markers here."})
    make_startup("beta-labs", {"data-room/secret.pdf": "<!-- sictic-page:1 -->\nBeta secret.\n"})
    config = load_repository_config("dd_checks")
    return DdReview(
        startup="Alpha Bio",
        data_room=DataRoom.for_startup("alpha-bio", SETTINGS),
        dd_config=config,
        response_schema=config["audit_response_schema"],
    )


def fill_all(review, product_type="software"):
    review.get_checklists(product_type)
    for number in review.expected_checks():
        assert review.record_check(number, json.dumps(valid_result())).startswith("Recorded")


def test_documents_are_the_startups_current_sources_with_pages(review):
    listing = review.data_room.list_documents()

    assert "- data-room/deck.pdf (pages 1-3," in listing
    assert "- data-room/notes.md (no page numbers," in listing
    assert "secret" not in listing


def test_read_document_returns_the_requested_pages(review):
    text = review.data_room.read_document("data-room/deck.pdf", 2, 3)

    assert "## data-room/deck.pdf, page 2\n\nThe cap table lists two founders." in text
    assert "page 3" in text
    assert "diagnostic test" not in text
    assert review.data_room.documents_read == {"data-room/deck.pdf"}


@pytest.mark.parametrize("document", [
    "data-room/secret.pdf",
    "../beta-labs/datasets/data-room/secret.pdf",
    "storage/startups/beta-labs/datasets/data-room/secret.pdf",
    "data-room/deck.pdf.md",
])
def test_read_document_rejects_anything_outside_the_startups_sources(review, document):
    assert review.data_room.read_document(document, None, None).startswith("Unknown document")
    assert review.data_room.documents_read == set()


def test_read_document_stops_at_the_reading_limit(review):
    review.data_room.max_read_characters = 80

    text = review.data_room.read_document("data-room/deck.pdf", None, None)

    assert "page 1" in text
    assert "Call read_document with first_page=2 to continue." in text


def test_search_text_returns_document_page_and_excerpt(review):
    assert "- data-room/deck.pdf, page 2: …The cap table lists two founders.…" in (
        review.data_room.search_text("cap table")
    )
    # An invalid regular expression is searched as plain text.
    assert review.data_room.search_text("CHF 120k (").startswith("No matches")
    assert "page 3" in review.data_room.search_text("CHF 120k")
    review.data_room.max_search_results = 1
    assert "More matches exist" in review.data_room.search_text("a")


def test_checklists_match_the_dd_checks_selection_and_numbering(review):
    config = review.dd_config
    chapters, _types = checklist_chapters_and_types(config)

    listing = review.get_checklists("Software")

    expected = [parse_checklist(markdown) for _chapter, markdown in select_checklists(config, chapters, "software")]
    assert [checklist for _chapter, checklist in review.checklists] == expected
    assert all(checklist.title in listing for checklist in expected)
    assert review.get_checklists("rocket science").startswith("Unknown product type")


def test_product_type_cannot_change_after_checks_are_recorded(review):
    review.get_checklists("software")
    first = next(iter(review.expected_checks()))
    review.record_check(first, json.dumps(valid_result()))

    assert "cannot change" in review.get_checklists("biology")
    assert review.product_type == "software"


def test_record_check_validates_number_json_and_schema(review):
    assert review.record_check("1.1.1", "{}").startswith("No checklists selected")
    review.get_checklists("general")
    number = next(iter(review.expected_checks()))

    assert review.record_check("99.9.9", json.dumps(valid_result())).startswith("Unknown check number")
    assert "not valid JSON" in review.record_check(number, "{status: Fine")
    invalid = valid_result()
    invalid["importance"] = 11
    assert "does not match the schema" in review.record_check(number, json.dumps(invalid))
    assert number not in review.results
    assert review.record_check(number, json.dumps(valid_result())).startswith(f"Recorded check {number}.")
    assert number not in review.missing_checks()


def test_get_checklist_lists_checks_and_marks_recorded_ones(review):
    review.get_checklists("general")
    title = review.checklists[0][1].title
    number = next(iter(review.expected_checks()))
    review.record_check(number, json.dumps(valid_result()))

    text = review.get_checklist(title)

    assert text.startswith(f"# {title}")
    assert f"{number} " in text and "(recorded)" in text
    assert review.get_checklist("unknown").startswith("Unknown checklist")


def test_priorities_need_all_checks_and_content(review):
    review.get_checklists("general")
    assert review.submit_priorities("## 1. Something").startswith("Record all checks first")
    fill_all(review, "general")
    assert review.submit_priorities("  ").startswith("The priorities are empty")
    assert review.submit_priorities("## 1. Unverified cash\n") == "Priorities saved."
    assert review.priorities == "## 1. Unverified cash"


def test_follow_up_names_what_is_missing(review):
    assert "get_checklists" in follow_up_message(review)
    review.get_checklists("general")
    missing = review.missing_checks()
    assert missing[0] in follow_up_message(review)
    fill_all(review, "general")
    assert "submit_priorities" in follow_up_message(review)
    review.submit_priorities("## 1. Priority")
    assert follow_up_message(review) is None


def test_audit_documents_pass_validation_and_render(review):
    fill_all(review)

    documents = review.audit_documents(MODEL)

    assert len(documents) == len(review.checklists)
    for checklist, document in documents:
        assert validate_audit_document(document, require_complete=True) is document
        assert document["checklist_title"] == checklist.title
        insight = SimpleNamespace(content=lambda document=document: json.dumps(document))
        assert "| No | Check | Status | Importance |" in json_to_markdown_table(insight)


REPORT = "storage/startups/alpha-bio/insights/dd-checks-alpha-bio-test-model-1b.md"
PRIORITIES = "storage/startups/alpha-bio/insights/dd-priorities-alpha-bio-test-model-1b.md"


@pytest.fixture
def fake_run(review, monkeypatch):
    """Replace the agent run by one that records every check and the priorities."""
    calls = []

    async def no_import(*_args, **_kwargs):
        return SimpleNamespace(dataset_slug="alpha-bio")

    async def no_sync(*_args, **_kwargs):
        return []

    async def run_review(state, _config):
        calls.append(state)
        fill_all(state)
        state.data_room.read_document("data-room/deck.pdf", None, None)
        state.submit_priorities("## 1. Unverified cash\n\n**Verified:** Deck page 3.")
        return TokenUsage(requests=3, input_tokens=900, output_tokens=100, total_tokens=1000), False

    monkeypatch.setattr("lib.startups.sources.ensure_startup_dataset", no_import)
    monkeypatch.setattr(dd_checks_module, "sync_datasets", no_sync)
    monkeypatch.setattr(module, "llm_model", lambda: MODEL)
    # The agent module imports the SDK wiring only for a run; replace it without the SDK.
    monkeypatch.setitem(sys.modules, "skills.dd_checks.agent_runner", SimpleNamespace(run_review=run_review))
    return calls


def test_the_agent_is_the_configured_dd_engine(mock_env):
    assert dd_checks_module.dd_engine(load_repository_config("dd_checks")) == "agent"
    with pytest.raises(ValueError, match="must be one of agent, pipeline"):
        dd_checks_module.dd_engine({"settings": {"engine": "chat"}})


@pytest.mark.asyncio
async def test_dd_checks_agent_saves_report_priorities_and_audits(fake_run):
    [report] = await dd_checks("Alpha Bio")

    assert report.path == REPORT
    text = report.content()
    assert text.startswith("# M&A Due Diligence Checks for Alpha Bio")
    assert "**Product type:** software" in text
    assert "## Most important findings" in text
    assert "## Chapter: 1_elevator" in text
    assert "**Verified:** Deck page 3." in get_storage().read_text(PRIORITIES)
    audits = get_storage().list("storage/startups/alpha-bio/insights/batch-audit", suffix=".json")
    assert len(audits) == len(fake_run[0].checklists)
    assert all(name.startswith("dd-checks-") for name in audits)
    for name in audits:
        audit = json.loads(get_storage().read_text(f"storage/startups/alpha-bio/insights/batch-audit/{name}"))
        assert audit["skill"] == "dd_checks"


@pytest.mark.asyncio
async def test_dd_checks_agent_reuses_results_and_a_manual_report(fake_run):
    await dd_checks("alpha-bio")
    [report] = await dd_checks("alpha-bio")
    assert len(fake_run) == 1
    assert report.path == REPORT

    # Without reusable priorities the agent runs again.
    get_storage().remove(PRIORITIES)
    await dd_checks("alpha-bio")
    assert len(fake_run) == 2

    manual = InsightFile("alpha-bio", "dd_checks", "manual")
    manual.save("# Reviewed DD report")
    [report] = await dd_checks("alpha-bio")
    assert report.path == manual.path
    assert len(fake_run) == 2


@pytest.mark.asyncio
async def test_unfinished_agent_run_raises_and_saves_nothing(fake_run, monkeypatch):
    async def unfinished(state, _config):
        state.get_checklists("software")
        return TokenUsage(), True

    monkeypatch.setitem(sys.modules, "skills.dd_checks.agent_runner", SimpleNamespace(run_review=unfinished))

    with pytest.raises(RuntimeError, match="checks not recorded"):
        await dd_checks("alpha-bio")
    assert not get_storage().exists(REPORT)
    assert not get_storage().exists(PRIORITIES)


@pytest.mark.asyncio
async def test_dd_priorities_returns_the_agents_priorities_without_a_model_call(fake_run, monkeypatch):
    async def no_model_call(_prompt):
        raise AssertionError("The agent's priorities need no synthesis.")

    monkeypatch.setattr("skills.dd_priorities.dd_priorities.generate_markdown", no_model_call)
    monkeypatch.setattr("skills.dd_priorities.dd_priorities.llm_model", lambda: MODEL)
    await dd_checks("alpha-bio")

    [priorities] = await dd_priorities("alpha-bio")

    assert priorities.path == PRIORITIES
    assert "Unverified cash" in priorities.content()


@pytest.mark.asyncio
async def test_dd_priorities_asks_for_a_new_run_when_the_data_room_changed(fake_run, monkeypatch):
    monkeypatch.setattr("skills.dd_priorities.dd_priorities.llm_model", lambda: MODEL)
    await dd_checks("alpha-bio")
    manifest = IngestionManifest(get_storage(), dataset_location_for_domain("alpha-bio", "startups").parsed_rel)
    manifest.indexed_dataset_revision = "revision-2"
    manifest.save()

    with pytest.raises(ValueError, match="Run /dd_checks alpha-bio"):
        await dd_priorities("alpha-bio")


def test_agent_tools_are_limited_to_the_data_room_and_review(review):
    from skills.dd_checks.agent_runner import build_agent

    config = load_repository_config()
    agent = build_agent(review, "litellm/openai/test", config)

    assert [tool.name for tool in agent.tools] == [
        "list_documents", "read_document", "search_text", "get_checklists",
        "assess_checklist", "recorded_checks", "submit_priorities",
    ]
    assert "{{" not in agent.instructions


@pytest.mark.asyncio
async def test_agent_model_calls_wait_for_the_scheduler_and_count_tokens(mock_env, monkeypatch):
    from agents.extensions.models.litellm_model import LitellmModel
    from agents.usage import InputTokensDetails, Usage
    from lib.infrastructure.ai_text_generation import agent_model as agent_model_module
    from lib.infrastructure.scheduler_operations import inspect_operation

    async def fake_response(self, system_instructions, input, *args, **kwargs):
        return SimpleNamespace(usage=Usage(
            requests=1, input_tokens=600, output_tokens=100, total_tokens=700,
            input_tokens_details=InputTokensDetails(cached_tokens=400, cache_write_tokens=0),
        ))

    scheduled = []

    class RecordingScheduler:
        async def run(self, operation, *, operation_kwargs):
            scheduled.append(inspect_operation(operation, operation_kwargs))
            return await operation(**operation_kwargs)

    monkeypatch.setattr(LitellmModel, "get_response", fake_response)
    monkeypatch.setattr(agent_model_module, "scheduler", RecordingScheduler())
    monkeypatch.setenv("LLM_MODEL", "openai/test-model")
    usage = TokenUsage()
    model = agent_model_module.agent_model(1000, usage)

    await model.get_response("Assess.", [{"role": "user", "content": "Start."}])
    with pytest.raises(TokenBudgetExceeded, match="1400 tokens"):
        await model.get_response("Assess.", "Continue.")
    assert usage.requests == 2
    assert usage.total_tokens == 1400
    assert usage.cached_input_tokens == 800
    assert [(job.kind, job.descriptor) for job in scheduled] == [("llm_agent", "openai/test-model")] * 2
    assert scheduled[0].input_size == len("Assess.") + len('[{"role": "user", "content": "Start."}]')
    assert scheduled[1].input_size == len("Assess.") + len("Continue.")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["rate limit", "hung request"])
async def test_agent_run_retries_a_failed_model_call(failure):
    import asyncio

    import httpx
    import openai
    from agents import Agent, RunConfig, Runner
    from agents.extensions.models.litellm_model import LitellmModel
    from agents.items import ModelResponse
    from agents.usage import Usage
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText
    from lib.infrastructure.ai_text_generation.agent_model import agent_model_settings

    calls = []

    class FailingOnceModel(LitellmModel):
        async def get_response(self, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1 and failure == "rate limit":
                request = httpx.Request("POST", "https://example.invalid")
                raise openai.RateLimitError(
                    "Rate limit", response=httpx.Response(429, request=request), body=None,
                )
            if len(calls) == 1:
                # Longer than the request timeout below.
                await asyncio.sleep(5)
            message = ResponseOutputMessage(
                id="message-1", type="message", role="assistant", status="completed",
                content=[ResponseOutputText(type="output_text", text="done", annotations=[])],
            )
            return ModelResponse(output=[message], usage=Usage(requests=1), response_id=None)

    settings = agent_model_settings(0.1)
    settings.retry.backoff.initial_delay = 0
    agent = Agent(
        name="Test agent", instructions="Answer.",
        model=FailingOnceModel(model="openai/test-model"), model_settings=settings,
    )
    result = await Runner.run(agent, "Start.", run_config=RunConfig(tracing_disabled=True))

    assert result.final_output == "done"
    assert len(calls) == 2
