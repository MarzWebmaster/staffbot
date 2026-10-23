"""LLM proxy: the only path from customer Hermes containers to LLM providers.

Run as its own service (same image as the API):
    uvicorn app.llm_proxy.main:app --host 0.0.0.0 --port 8090

See docs/TARGET_ARCHITECTURE.md §8.
"""
