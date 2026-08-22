"""
Product Manager Agent
Converts the Requirements Analyst's FR list into Epic -> User Story -> Task
breakdown (PDF section 6). Deterministic (no LLM call) so it never adds a
rate-limit hit or a new failure surface -- it's a structured transform of
data AURA already has.
"""


def _slug(text: str, max_len: int = 24) -> str:
    words = "".join(c if c.isalnum() or c == " " else "" for c in text).split()
    return "-".join(w.lower() for w in words[:4])[:max_len]


def build_plan(spec: dict) -> dict:
    """
    Turns functional_requirements into an Epic/Story/Task tree.
    One epic per FR (this MVP treats each FR as its own feature slice;
    grouping multiple FRs under a shared epic can be added once FRs
    start carrying an explicit 'epic' field from the Requirements Analyst).
    """
    epics = []
    for fr in spec.get("functional_requirements", []):
        epic_id = f"EPIC-{fr['id'].split('-')[1]}"
        story_id = f"STORY-{fr['id'].split('-')[1]}"
        tasks = [
            {"id": f"{story_id}-T1", "title": f"Implement: {fr['description']}"},
            {"id": f"{story_id}-T2", "title": "Write tests covering the acceptance criteria"},
        ]
        epics.append({
            "epic_id": epic_id,
            "epic_title": fr["description"],
            "story_id": story_id,
            "story": f"As a user, I want {_slug(fr['description'], 60) or fr['description']}, "
                     f"so that the requirement is satisfied.",
            "tasks": tasks,
            "source_fr": fr["id"],
        })
    return {"epics": epics}


def print_plan(plan: dict) -> None:
    print("--- Product Manager: epic/story breakdown ---")
    if not plan["epics"]:
        print("  (no functional requirements to plan)")
        print()
        return
    for epic in plan["epics"]:
        print(f"  {epic['epic_id']}: {epic['epic_title']}")
        print(f"    {epic['story_id']}: {epic['story']}")
        for task in epic["tasks"]:
            print(f"      {task['id']}: {task['title']}")
    print()
