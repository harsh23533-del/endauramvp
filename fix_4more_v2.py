path = "core/orchestrator.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

import re

def replace_before(content, anchor, block_lines_no_indent):
    m = re.search(r"^([ \t]*)" + re.escape(anchor), content, re.MULTILINE)
    if not m:
        raise SystemExit(f"Anchor not found: {anchor!r}")
    ind = m.group(1)
    full_line = ind + anchor
    new_block = "".join(f"{ind}{line}\n" for line in block_lines_no_indent)
    return content.replace(full_line, new_block + full_line, 1), ind

def replace_after(content, anchor, block_lines_no_indent):
    m = re.search(r"^([ \t]*)" + re.escape(anchor), content, re.MULTILINE)
    if not m:
        raise SystemExit(f"Anchor not found: {anchor!r}")
    ind = m.group(1)
    full_line = ind + anchor
    new_block = "".join(f"\n{ind}{line}" for line in block_lines_no_indent)
    return content.replace(full_line, full_line + new_block, 1), ind

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

# A: imports + memory recall, inserted BEFORE anchor 0
content, _ = replace_before(content, anchors[0], [
    "from core.product_manager import build_plan, print_plan",
    "from core.performance_agent import scan as performance_scan, print_performance",
    "from core.project_memory import load_memory, save_memory, print_memory_context",
    "from core.episodic_memory import log_episode, print_recent_episodes",
    "_memory = load_memory()",
    "print_memory_context(_memory)",
    "print_recent_episodes()",
])

# B: product manager, inserted AFTER anchor 1
content, _ = replace_after(content, anchors[1], [
    "product_plan = build_plan(requirements_spec)",
    "print_plan(product_plan)",
])

# C: save project memory, inserted AFTER anchor 2
content, _ = replace_after(content, anchors[2], [
    "save_memory(user_request, architecture)",
])

# D: performance scan, inserted AFTER anchor 3
content, _ = replace_after(content, anchors[3], [
    "performance_result = performance_scan(written_files)",
    "print_performance(performance_result)",
])

# E: episodic memory logging, inserted AFTER anchor 4
content, _ = replace_after(content, anchors[4], [
    "log_episode(user_request, diagnosis.get('root_cause', 'unknown'), "
    "diagnosis.get('fix_summary', diagnosis.get('description', 'patch applied')))",
])

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("orchestrator.py patched successfully - 5 insertions applied")
