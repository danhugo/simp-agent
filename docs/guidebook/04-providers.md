# 04 Part 1 · Providers

> Skeleton only. Prose not written yet.

**Goal:** Talk to real models through one small registry.

**Builds on:** [03-stream-parser](03-stream-parser.md) · **Next:** [05-agent-loop](05-agent-loop.md)

## Planned sections

- Registry and lazy loading (_PROVIDERS, register_provider, stream)
- OpenAI completions and responses
- Anthropic
- transform_messages and thinking
- Error classification: is_retryable, is_context_overflow

## Code it covers

- `packages/simp_agent/src/simp_agent/ai/__init__.py`
- `packages/simp_agent/src/simp_agent/ai/providers/anthropic.py`
- `packages/simp_agent/src/simp_agent/ai/providers/openai_completions.py`
- `packages/simp_agent/src/simp_agent/ai/providers/openai_responses.py`

## Test it will show

- `packages/simp_agent/tests/test_openai.py, test_reasoning.py`
