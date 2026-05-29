"""Cleanup helpers for short-lived LiteLLM CLI processes."""


async def close_litellm_sessions() -> None:
    """Close LiteLLM's process-global aiohttp session when present.

    LiteLLM keeps an aiohttp session on a module-level handler for some OpenAI-
    compatible paths. That is fine for daemons, but one-shot CLI commands exit
    immediately and Python reports the still-open session. Closing it explicitly
    keeps harness output readable.
    """
    try:
        import litellm.main as litellm_main

        handler = getattr(litellm_main, "base_llm_aiohttp_handler", None)
        session = getattr(handler, "client_session", None)
        if session is not None and not session.closed:
            await session.close()
            handler.client_session = None
    except Exception:
        pass

    try:
        import gc
        import warnings
        import aiohttp

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sessions = [
                obj
                for obj in gc.get_objects()
                if isinstance(obj, aiohttp.ClientSession) and not obj.closed
            ]
        for session in sessions:
            await session.close()
    except Exception:
        pass
