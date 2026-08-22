path = "core/orchestrator.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

import re

def get_indent(anchor, content):
    m = re.search(r"([ \t]*)" + re.escape(anchor), content)
    if not m:
        return None
    return m.group(1)

anchors = [
    "requirements_spec = analyze_requirements(user_request)",
    "print_requirements(requirements_spec)",
    "architecture = architect_design(user_request)",
    "security_result = security_scan(written_files)",
    'diagnosis = debug(user_request, written_files, test_result["raw_output"])',
]
for a in anchors:
    c = content.count(a)
    if c != 1:
        raise SystemExit(f"Anchor not unique (found {c}): {a!r} -- aborting, no changes made.")

indents = {a: get_indent(a, content) for a in anchors}

# A: imports + memory recall, inserted BEFORE anchor 0
ind = indents[anchors[0]]
block_a = (
    f"{ind}from core.product_manager import build_plan, print_plan\n"
    f"{ind}from core.performance_agent import scan as performance_scan, print_performance\n"
    f"{ind}from core.project_memory import load_memory, save_memory, print_memory_context\n"
    f"{ind}from core.episodic_memory import log_episode, print_recent_episodes\n"
    f"{ind}_memory = load_memory()\n"
    f"{ind}print_memory_context(_memory)\n"
    f"{ind}print_recent_episodes()\n"
)
content = content.replace(anchors[0], block_a + ind + anchors[0], 1)

# B: product manager, inserted AFTER anchor 1
ind = indents[anchors[1]]
block_b = (
    f"\n{ind}product_plan = build_plan(requirements_spec)\n"
    f"{ind}print_plan(product_plan)"
)
content = content.replace(anchors[1], anchors[1] + block_b, 1)

# C: save project memory, inserted AFTER anchor 2
ind = indents[anchors[2]]
block_c = f"\n{ind}save_memory(user_request, architecture)"
content = content.replace(anchors[2], anchors[2] + block_c, 1)

# D: performance scan, inserted AFTER anchor 3
ind = indents[anchors[3]]
block_d = (
    f"\n{ind}performance_result = performance_scan(written_files)\n"
    f"{ind}print_performance(performance_result)"
)
content = content.replace(anchors[3], anchors[3] + block_d, 1)

# E: episodic memory logging, inserted AFTER anchor 4
ind = indents[anchors[4]]
block_e = (
    f"\n{ind}log_episode(user_request, diagnosis.get('root_cause', 'unknown'), "
    f"diagnosis.get('fix_summary', diagnosis.get('description', 'patch applied')))"
)
content = content.replace(anchors[4], anchors[4] + block_e, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("orchestrator.py patched successfully - 5 insertions applied")
