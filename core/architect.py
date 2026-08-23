"""
Architect agent.
Decides the technical approach before planning begins.

PDF section 46 -- parallel architecture search: proposes 2-3 full
candidate stacks, each pre-scored by the LLM across cost/complexity/
performance/security/maintainability, and deterministically picks the
highest-scoring one in code (never trusting the model to self-select --
consistent with the rest of this codebase keeping decision logic out
of the LLM wherever it can be). This stops short of actually BUILDING
out all 2-3 candidates end-to-end (that would multiply LLM/API cost
per build for an MVP that already runs on free-tier rate limits) --
it's architecture-level search, not full parallel implementation.
"""
from core.llm import call_claude_json

ARCHITECT_SYSTEM_PROMPT = """You are the Architect agent inside AURA, an autonomous \
software engineering system.

Given a user's request, propose 2-3 candidate technical approaches (language, \
framework, whether a database is needed, key libraries) and score EACH one.

Rules:
- Keep every candidate minimal -- this is an MVP, not a full product.
- Only mark needs_database true if the request clearly needs persistent structured data.
- Propose 1 candidate only if there's really just one sane choice -- don't pad with a
  strictly worse option just to reach 2.
- Score each candidate 0-100 considering cost, complexity, performance, security, and
  maintainability for THIS specific request -- scores should meaningfully differ, not
  all cluster near the same number.
- Respond ONLY with valid JSON, no markdown fences, no preamble.
- Format:
{
  "candidates": [
    {
      "stack": {"language": "python", "framework": "flask"},
      "needs_database": false,
      "notes": "one or two sentences justifying this candidate",
      "score": 88
    },
    {
      "stack": {"language": "node", "framework": "express"},
      "needs_database": false,
      "notes": "why this is viable but scored lower",
      "score": 71
    }
  ]
}
"""


def design(user_request: str) -> dict:
    result = call_claude_json(
        system=ARCHITECT_SYSTEM_PROMPT,
        user_message=user_request,
        max_tokens=1200,
        role="reasoning",
    )

    candidates = result.get("candidates", [])
    if not candidates:
        # Malformed/old-shape response -- treat the whole result as a
        # single candidate rather than failing the build over it.
        return result

    candidates_sorted = sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)
    chosen = candidates_sorted[0]
    rejected = candidates_sorted[1:]

    return {
        "stack": chosen.get("stack", {}),
        "needs_database": chosen.get("needs_database", False),
        "notes": chosen.get("notes", ""),
        "score": chosen.get("score"),
        "alternatives_considered": [
            {"stack": c.get("stack"), "reason_rejected": f"scored {c.get('score')} vs chosen {chosen.get('score')} -- {c.get('notes', '')}"}
            for c in rejected
        ],
        "candidates": candidates_sorted,
    }
