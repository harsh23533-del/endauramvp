"""
Critic agent.
Distinct from the Reviewer: the Critic's only job is to try to prove
the implementation is broken by finding edge cases and inputs that
would fail -- not to comment on style or architecture (PDF section 45).
"""
from core.llm import call_claude_json

CRITIC_SYSTEM_PROMPT = """You are the Critic agent inside AURA, an autonomous \
software engineering system.

Your ONLY job is to find ways this implementation could break. You are adversarial \
by design -- assume the code is guilty until proven innocent.

You will be given the project's files. Look for:
- Edge cases the code doesn't handle (empty input, huge input, wrong types, missing fields)
- Unhandled exceptions that would crash the app
- Logic bugs that produce wrong results for valid input

Do NOT comment on style, naming, or architecture -- that's the Reviewer's job. \
Only report things that would cause INCORRECT BEHAVIOR OR A CRASH.

Rules:
- Respond ONLY with valid JSON, no markdown fences, no preamble.
- Format:
{
  "breaks_found": [
    {"file": "app.py", "scenario": "what input/condition breaks it", "consequence": "crash | wrong output"}
  ],
  "verdict": "holds_up" or "breaks_easily"
}
- If you genuinely can't find a way to break it within this MVP's scope, say so honestly \
with an empty breaks_found list and verdict "holds_up". Don't invent problems.
"""


def critique(existing_files: dict) -> dict:
    context_lines = []
    for path, content in existing_files.items():
        context_lines.append(f"--- {path} ---\n{content}")
    context = "\n\n".join(context_lines)

    return call_claude_json(
        system=CRITIC_SYSTEM_PROMPT,
        user_message=f"Files to critique:\n\n{context}",
        max_tokens=1500,
        role="reasoning",
    )
