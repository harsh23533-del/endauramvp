path = "core/orchestrator.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# lines are 0-indexed here; file lines 31-35 correspond to index 30-34
start = 30
end = 35

new_block = [
    '    from core.requirements_agent import analyze_requirements, print_requirements\n',
    '    requirements_spec = analyze_requirements(user_request)\n',
    '    print_requirements(requirements_spec)\n',
    '    architecture = architect_design(user_request)\n',
]

lines[start:end] = new_block

with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)

print("Fixed lines", start+1, "to", end)
