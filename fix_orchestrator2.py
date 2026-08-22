import re

path = "core/orchestrator.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

marker = "architecture = architect_design(user_request)"
if marker not in content:
    raise SystemExit("Marker line not found - paste file content for manual check.")

indent_match = re.search(r"([ \t]*)" + re.escape(marker), content)
indent = indent_match.group(1)

insertion = (
    f"{indent}from core.requirements_agent import analyze_requirements, print_requirements\n"
    f"{indent}requirements_spec = analyze_requirements(user_request)\n"
    f"{indent}print_requirements(requirements_spec)\n"
)

content = content.replace(marker, insertion + marker, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Patched successfully")
