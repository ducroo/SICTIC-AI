from lib.insights.file import InsightFile


def save_report(dataset: str, content: str, prompt_key: str) -> str:
    """Persist an agent-authored dd_checks report through InsightFile."""
    insight = InsightFile(
        dataset=dataset,
        skill="dd_checks",
        model="anthropic/claude-code-agent",
        prompt_key=prompt_key,
    )
    insight.save(content)
    return insight.path
