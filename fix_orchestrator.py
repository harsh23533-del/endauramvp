import re

path = "core/orchestrator.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

bad_line = "from core.requirements_agent import analyze_requirements, print_requirements\n"
lines = [ln for ln in lines if ln.strip() != bad_line.strip()]

lines = [ln for ln in lines if ln.strip() not in (
    "requirements_spec = analyze_requirements(user_request)",
    "print_requirements(requirements_spec)",
)]

new_lines = []
for ln in lines:
    if "architect_design(user_request)" in ln and "=" in ln:
        indent = re.match(r"^(\s*)", ln).group(1)
        new_lines.append(f"{indent}from core.requirements_agent import analyze_requirements, print_requirements\n")
        new_lines.append(f"{indent}requirements_spec = analyze_requirements(user_request)\n")
        new_lines.append(f"{indent}print_requirements(requirements_spec)\n")
    new_lines.append(ln)

with open(path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Patched orchestrator.py")