"""LLM provider abstraction.

Cycle 0 carries the legacy provider modules forward to keep current
behavior working. Cycle 2 introduces the `Provider` Protocol, the
cost/latency-tracked router, and Anthropic/Ollama providers.
"""
