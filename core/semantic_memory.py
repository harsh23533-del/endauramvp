"""
Semantic memory (PDF section 25's fourth memory type -- distinct from
Project memory, which is per-project and already covered by
core/project_memory.py).

Section 25's own definition is "general knowledge -- React, FastAPI,
PostgreSQL, Docker, Security practices" -- knowledge that's true
across EVERY project, not something learned from this one. A full
knowledge base isn't warranted at this scale (the underlying LLM
already carries this knowledge); what's genuinely missing and worth
codifying is a short, curated, house-style checklist AURA always
applies regardless of which stack the Architect picked -- so quality
bar doesn't depend on the model happening to recall it unprompted.
"""

BACKEND_KNOWLEDGE = """Backend best practices AURA always applies, regardless of framework:
- Validate and sanitize all external input before using it in a query, file path, or shell command.
- Never build SQL by string concatenation -- use parameterized queries.
- Hash passwords (bcrypt/argon2), never store or log them in plaintext.
- Return proper HTTP status codes (400 for bad input, 401/403 for auth, 404, 500 only for real server errors).
- Don't leak stack traces or internal error detail to the client in responses."""

FRONTEND_KNOWLEDGE = """Frontend best practices AURA always applies:
- Escape/encode any user-supplied content before rendering it (avoid XSS).
- Use semantic HTML elements and label every form input for accessibility.
- Never hardcode secrets or API keys into client-side JS.
- Handle both the loading and error states of every network request, not just the happy path."""

SECURITY_KNOWLEDGE = """Security practices referenced during review/scan (aligned with OWASP Top 10):
- Injection (SQL, command, template) -- untrusted input reaching an interpreter unsanitized.
- Broken authentication/session handling -- weak password storage, predictable session tokens.
- Sensitive data exposure -- secrets in code, verbose error messages, missing encryption.
- Broken access control -- missing authorization checks on an endpoint or resource."""

_KNOWLEDGE_BY_ROLE = {
    "backend": BACKEND_KNOWLEDGE,
    "frontend": FRONTEND_KNOWLEDGE,
    "security": SECURITY_KNOWLEDGE,
}


def get_knowledge(role: str) -> str:
    return _KNOWLEDGE_BY_ROLE.get(role, "")
