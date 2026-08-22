"""
Evaluation Engine.
Turns a build report into a single, comparable AURA Score -- so
"did it work" isn't just pass/fail, it's a breakdown across the
dimensions that actually matter for a real build (PDF section 32/36).
"""


def score(report: dict) -> dict:
    scores = {}

    # Requirements coverage: how many planned files actually got written.
    planned = report.get("planned_file_count", 0)
    written = len(report.get("files_written", []))
    scores["requirements"] = round(100 * written / planned) if planned else 100

    # Tests: prefer the actual pass/fail counts pytest reported.
    test_result = report.get("test_result", {})
    passed_n = test_result.get("passed_count", 0)
    failed_n = test_result.get("failed_count", 0)
    error_n = test_result.get("error_count", 0)
    total = passed_n + failed_n + error_n
    if total > 0:
        scores["tests"] = round(100 * passed_n / total)
    else:
        scores["tests"] = 100 if test_result.get("passed") else 0

    # Security: deduct per finding from the static scan.
    security_result = report.get("security_result", {})
    findings = len(security_result.get("findings", []))
    scores["security"] = max(0, 100 - 15 * findings)

    # Code quality: deduct per reviewer issue; 50 if the reviewer
    # itself failed to run (unknown, not zero -- don't punish for
    # an LLM hiccup we couldn't recover from).
    review_result = report.get("review_result", {})
    approved = review_result.get("approved")
    issues = len(review_result.get("issues", []))
    scores["code_quality"] = 50 if approved is None else max(0, 100 - 10 * issues)

    weights = {"requirements": 0.25, "tests": 0.35, "security": 0.20, "code_quality": 0.20}
    overall = sum(scores[k] * w for k, w in weights.items())
    scores["overall"] = round(overall, 1)

    return scores


def format_scorecard(scores: dict) -> str:
    lines = [
        "AURA SCORE",
        f"  Requirements  : {scores['requirements']}%",
        f"  Tests         : {scores['tests']}%",
        f"  Security      : {scores['security']}%",
        f"  Code Quality  : {scores['code_quality']}%",
        f"  ------------------------",
        f"  Overall       : {scores['overall']}%",
    ]
    return "\n".join(lines)
