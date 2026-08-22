"""
Requirements Analyst Agent
Converts a raw natural-language request into a structured, executable
specification: functional requirements, non-functional requirements,
and acceptance criteria. This becomes the contract every later agent
(Architect, Coder, Tester, Reviewer) can be checked against.
"""

import json
import re

from core.llm import call_claude

REQUIREMENTS_SYSTEM_PROMPT = """You are the Requirements Analyst agent inside an autonomous \
software engineering system called AURA.

Given a raw user request, produce a structured specification. Respond with ONLY a JSON object \
(no markdown fences, no commentary) in exactly this shape:

{
  "functional_requirements": [
    {"id": "FR-001", "description": "..."}
  ],
  "non_functional_requirements": [
    {"id": "NFR-001", "description": "..."}
  ],
  "acceptance_criteria": [
    {"id": "AC-001", "requirement_id": "FR-001", "given": "...", "when": "...", "then": "..."}
  ]
}

Rules:
- IDs must be sequential and zero-padded to 3 digits (FR-001, FR-002, ...).
- Keep the list proportional to the request: a simple request ("a /hello endpoint") should \
produce a SHORT list (1-3 FRs), not an enterprise-scale spec.
- Every functional requirement should be testable.
- Include at least one non-functional requirement (e.g. response time, input validation) unless \
the request is trivial enough that none apply.
- Do not invent scope the user did not ask for.
"""


def _clean_json(raw_text: str) -> str:
    """Strip markdown code fences and leading/trailing junk around a JSON object."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def analyze_requirements(user_request: str) -> dict:
    """
    Calls the LLM to turn a raw request into FR-/NFR-/AC- items.
    Returns a dict with keys: functional_requirements, non_functional_requirements,
    acceptance_criteria. Falls back to a minimal single-FR spec if parsing fails,
    so a bad LLM response never crashes the whole build.
    """
    response_text = call_claude(
        system=REQUIREMENTS_SYSTEM_PROMPT,
        user_message=user_request,
        max_tokens=800,
    )

    cleaned = _clean_json(response_text)

    try:
        spec = json.loads(cleaned)
    except json.JSONDecodeError:
        spec = {
            "functional_requirements": [
                {"id": "FR-001", "description": user_request.strip()}
            ],
            "non_functional_requirements": [],
            "acceptance_criteria": [],
        }

    spec.setdefault("functional_requirements", [])
    spec.setdefault("non_functional_requirements", [])
    spec.setdefault("acceptance_criteria", [])
    return spec


def print_requirements(spec: dict) -> None:
    """Console output matching AURA's existing pipeline log style."""
    print("--- Requirements Analyst: analyzing request ---")
    for fr in spec["functional_requirements"]:
        print(f"  {fr['id']}: {fr['description']}")
    if spec["non_functional_requirements"]:
        print("  -- non-functional --")
        for nfr in spec["non_functional_requirements"]:
            print(f"  {nfr['id']}: {nfr['description']}")
    print()


def format_spec(spec: dict) -> str:
    """Render the spec as a Markdown document to save into workspace/."""
    lines = ["# Requirements Specification\n"]

    lines.append("## Functional Requirements")
    for fr in spec.get("functional_requirements", []):
        lines.append(f"- {fr.get('id')}: {fr.get('description')}")

    lines.append("\n## Non-Functional Requirements")
    for nfr in spec.get("non_functional_requirements", []):
        lines.append(f"- {nfr.get('id')}: {nfr.get('description')}")

    lines.append("\n## Acceptance Criteria")
    for ac in spec.get("acceptance_criteria", []):
        lines.append(
            f"- {ac.get('id')} ({ac.get('requirement_id')}): "
            f"Given {ac.get('given')}, When {ac.get('when')}, Then {ac.get('then')}"
        )

    return "\n".join(lines)
