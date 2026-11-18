"""OpenAI Agents SDK wiring of the DD agent: the agents, their tools and the run.

agent.py imports this module only for a run, so tests can replace it. The
tools call the startup-scoped methods of DataRoom and DdReview in agent.py.
"""

import json
from typing import Any

from agents import Agent, RunContextWrapper, Runner, function_tool, set_tracing_disabled

from lib.infrastructure.ai_text_generation.agent_model import (
    TokenUsage,
    agent_model,
    agent_model_settings,
)
from lib.infrastructure.logging import get_logger
from lib.model_config import llm_endpoint
from skills.dd_checks.agent import DdReview, fill_placeholders, follow_up_message
from skills.dd_checks.dd_checks import audit_instructions_with_context

logger = get_logger(__name__)


def build_agent(review: DdReview, model: Any, config: dict[str, Any]) -> Any:
    """Build the main agent and its checklist agent with tools scoped to the review."""
    def call(ctx: RunContextWrapper[DdReview], name: str, *args: Any) -> str:
        """Count the tool call and run it on the data room or the review state."""
        review_state = ctx.context
        review_state.tool_calls[name] += 1
        document_tools = {"list_documents", "read_document", "search_text"}
        target = review_state.data_room if name in document_tools else review_state
        return getattr(target, name)(*args)

    @function_tool
    def list_documents(ctx: RunContextWrapper[DdReview]) -> str:
        """List the startup's documents with their pages and length."""
        return call(ctx, "list_documents")

    @function_tool
    def read_document(
        ctx: RunContextWrapper[DdReview],
        document: str,
        first_page: int | None,
        last_page: int | None,
    ) -> str:
        """Read a document, or a range of its pages.

        Args:
            document: Document path exactly as shown by list_documents.
            first_page: First page to read, or null to start at the beginning.
            last_page: Last page to read, or null to read to the end.
        """
        return call(ctx, "read_document", document, first_page, last_page)

    @function_tool
    def search_text(ctx: RunContextWrapper[DdReview], pattern: str) -> str:
        """Search all documents for a word, phrase or regular expression, ignoring case.

        Args:
            pattern: Text or regular expression to find, for example "cap table|shareholder".
        """
        return call(ctx, "search_text", pattern)

    @function_tool
    def get_checklists(ctx: RunContextWrapper[DdReview], product_type: str) -> str:
        """Select the DD checklists for the startup's product type.

        Args:
            product_type: The product type from the classification rules, for example "software".
        """
        return call(ctx, "get_checklists", product_type)

    @function_tool
    def get_checklist(ctx: RunContextWrapper[DdReview], title: str) -> str:
        """Show every check of one checklist with its number and description.

        Args:
            title: Checklist title as returned by get_checklists.
        """
        return call(ctx, "get_checklist", title)

    @function_tool
    def record_check(ctx: RunContextWrapper[DdReview], number: str, result_json: str) -> str:
        """Record the result of one check.

        Args:
            number: Check number from get_checklist, for example "3.1.2".
            result_json: The result as a JSON object that matches the result schema.
        """
        return call(ctx, "record_check", number, result_json)

    @function_tool
    def recorded_checks(ctx: RunContextWrapper[DdReview]) -> str:
        """Show all checks with their recorded status, importance and rationale."""
        return call(ctx, "recorded_checks")

    @function_tool
    def submit_priorities(ctx: RunContextWrapper[DdReview], markdown: str) -> str:
        """Submit the final priorities as Markdown.

        Args:
            markdown: The complete priorities in the required format.
        """
        return call(ctx, "submit_priorities", markdown)

    dd_config = config["dd_checks"]
    settings = dd_config["settings"]["agent"]
    model_settings = agent_model_settings(settings["request_timeout_seconds"])

    def chapter_instructions(ctx: RunContextWrapper[DdReview], _agent: Any) -> str:
        state = ctx.context
        return fill_placeholders(
            dd_config["agent_chapter_instructions"],
            startup=state.startup,
            audit_instructions=audit_instructions_with_context(
                state.dd_config, state.product_type or "general",
            ),
            response_schema=json.dumps(state.response_schema, indent=2),
        )

    checklist_agent = Agent[DdReview](
        name="Checklist assessor",
        instructions=chapter_instructions,
        tools=[list_documents, read_document, search_text, get_checklist, record_check],
        model=model,
        model_settings=model_settings,
    )
    main_instructions = fill_placeholders(
        dd_config["agent_instructions"],
        startup=review.startup,
        industry_type_instructions=dd_config["industry_type_llm_instructions"],
        priorities_instructions=config["dd_priorities"]["llm_instructions"].replace(
            "{{startup}}", review.startup,
        ),
    )
    return Agent[DdReview](
        name="DD reviewer",
        instructions=main_instructions,
        tools=[
            list_documents,
            read_document,
            search_text,
            get_checklists,
            checklist_agent.as_tool(
                tool_name="assess_checklist",
                tool_description=(
                    "Assess and record every check of one checklist. Input: the "
                    "checklist title as returned by get_checklists."
                ),
                max_turns=settings["chapter_max_turns"],
                # Errors stop the run instead of becoming a vague tool message.
                failure_error_function=None,
            ),
            recorded_checks,
            submit_priorities,
        ],
        model=model,
        model_settings=model_settings,
    )


async def run_review(review: DdReview, config: dict[str, Any]) -> tuple[TokenUsage, bool]:
    """Run the agent, with one follow-up turn when it did not finish.

    Returns the token usage and whether the follow-up was needed.
    """
    # Keep prompts and documents out of OpenAI's tracing dashboard.
    set_tracing_disabled(True)
    settings = config["dd_checks"]["settings"]["agent"]
    usage = TokenUsage()
    agent = build_agent(review, agent_model(settings["max_total_tokens"], usage), config)
    startup_slug = review.data_room.startup_slug
    try:
        result = await Runner.run(
            agent, f"Review the startup {review.startup}.",
            context=review, max_turns=settings["max_turns"],
        )
        message = follow_up_message(review)
        if message is None:
            return usage, False
        logger.info("[%s] Agent did not finish; asking once more: %s", startup_slug, message)
        await Runner.run(
            agent, [*result.to_input_list(), {"role": "user", "content": message}],
            context=review, max_turns=settings["max_turns"],
        )
        return usage, True
    finally:
        # Logged also when the run fails, because the provider bills these tokens.
        logger.info("[%s] Agent model usage of %s: %s",
                    startup_slug, llm_endpoint().model, vars(usage))
