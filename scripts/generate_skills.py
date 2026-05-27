"""Generate comprehensive BUILTIN_SKILLS and BUILTIN_TOOLSETS for policy.py."""
import subprocess, json, os, re

HERMES_HOME = os.path.expanduser("~/.hermes")

def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30).stdout.strip()

# ── 1) Cybersecurity skills (754) from GitHub ────────────────
print("Fetching cybersecurity skills...")
raw = run("curl -sL 'https://api.github.com/repos/mukul975/Anthropic-Cybersecurity-Skills/contents/skills'")
cyber_names = []
if raw:
    try:
        data = json.loads(raw)
        cyber_names = [i['name'] for i in data if i.get('type') == 'dir']
    except:
        pass
print(f"  Got {len(cyber_names)} cybersecurity skills")

cyber_skills = []
for name in cyber_names:
    readable = name.replace('-', ' ').title()
    cyber_skills.append(
        f'    {{"id": "cyber-{name}", "name": "{readable}", "category": "cybersecurity", "desc": "{readable}", "default": False}}'
    )

# ── 2) Hermes Agent installed skills ─────────────────────────
print("Fetching Hermes installed skills...")
installed = []
skills_dir = f"{HERMES_HOME}/hermes-agent/skills"
for root, dirs, files in os.walk(skills_dir):
    if 'SKILL.md' in files:
        skill_name = os.path.basename(root)
        category = os.path.basename(os.path.dirname(root))
        # Read description
        desc_path = os.path.join(root, 'SKILL.md')
        desc = ""
        with open(desc_path) as f:
            for line in f:
                if line.startswith('description:'):
                    desc = line.replace('description:', '').strip().strip('"').strip("'")
                    desc = desc.replace('"', "'")
                    break
        if not desc:
            desc = skill_name.replace('-', ' ').title()
        installed.append((category, skill_name, desc))
print(f"  Got {len(installed)} installed skills")

hermes_installed_skills = []
for cat, name, desc in installed:
    desc_escaped = desc[:120]
    hermes_installed_skills.append(
        f'    {{"id": "{name}", "name": "{name.replace("-", " ").title()}", "category": "hermes-{cat}", "desc": "{desc_escaped}", "default": False}}'
    )

# ── 3) Hermes Agent optional skills ──────────────────────────
print("Fetching optional skills...")
optional = []
opt_dir = f"{HERMES_HOME}/hermes-agent/optional-skills"
if os.path.isdir(opt_dir):
    for cat in sorted(os.listdir(opt_dir)):
        cat_path = os.path.join(opt_dir, cat)
        if os.path.isdir(cat_path) and not cat.startswith('.'):
            for skill in sorted(os.listdir(cat_path)):
                skill_path = os.path.join(cat_path, skill, 'SKILL.md')
                if os.path.isfile(skill_path):
                    desc = ""
                    with open(skill_path) as f:
                        for line in f:
                            if line.startswith('description:'):
                                desc = line.replace('description:', '').strip().strip('"').strip("'")
                                desc = desc.replace('"', "'")
                                break
                    if not desc:
                        desc = skill.replace('-', ' ').title()
                    optional.append((cat, skill, desc))
print(f"  Got {len(optional)} optional skills")

hermes_optional_skills = []
for cat, name, desc in optional:
    desc_escaped = desc[:120]
    hermes_optional_skills.append(
        f'    {{"id": "opt-{name}", "name": "{name.replace("-", " ").title()}", "category": "{cat}", "desc": "{desc_escaped}", "default": False}}'
    )

# ── 4) Hub skills ────────────────────────────────────────────
print("Fetching hub skills...")
hub = []
hub_dir = f"{HERMES_HOME}/skills"
if os.path.isdir(hub_dir):
    for cat in sorted(os.listdir(hub_dir)):
        cat_path = os.path.join(hub_dir, cat)
        if os.path.isdir(cat_path) and not cat.startswith('.'):
            for skill in sorted(os.listdir(cat_path)):
                skill_path = os.path.join(cat_path, skill, 'SKILL.md')
                if os.path.isfile(skill_path):
                    desc = ""
                    with open(skill_path) as f:
                        for line in f:
                            if line.startswith('description:'):
                                desc = line.replace('description:', '').strip().strip('"').strip("'")
                                desc = desc.replace('"', "'")
                                break
                    if not desc:
                        desc = skill.replace('-', ' ').title()
                    hub.append((cat, skill, desc))
print(f"  Got {len(hub)} hub skills")

hub_skills = []
for cat, name, desc in hub:
    desc_escaped = desc[:120]
    hub_skills.append(
        f'    {{"id": "hub-{name}", "name": "{name.replace("-", " ").title()}", "category": "hub-{cat}", "desc": "{desc_escaped}", "default": False}}'
    )

# ── 5) Business skills from The CEO system (174 curated) ─────
# These are already in the current policy.py, we'll keep them between the imports and cybersecurity

# ── COUNT ────────────────────────────────────────────────────
total = len(cyber_skills) + len(hermes_installed_skills) + len(hermes_optional_skills) + len(hub_skills)
print(f"\n=== TOTAL: {total} auto-generated + 174 curated business = {total + 174} skills ===")
print(f"  Cybersecurity:      {len(cyber_skills)}")
print(f"  Hermes installed:   {len(hermes_installed_skills)}")
print(f"  Hermes optional:    {len(hermes_optional_skills)}")
print(f"  Hub:                {len(hub_skills)}")

# ── OUTPUT ───────────────────────────────────────────────────
out = f"""# Auto-generated skills from cybersecurity repo ({len(cyber_skills)})
CYBER_SKILLS = [
{chr(10).join(cyber_skills)},
]

# Auto-generated skills from Hermes Agent installed ({len(hermes_installed_skills)})
HERMES_INSTALLED_SKILLS = [
{chr(10).join(hermes_installed_skills)},
]

# Auto-generated skills from Hermes optional ({len(hermes_optional_skills)})
HERMES_OPTIONAL_SKILLS = [
{chr(10).join(hermes_optional_skills)},
]

# Auto-generated skills from Hub ({len(hub_skills)})
HUB_SKILLS = [
{chr(10).join(hub_skills)},
]
"""

with open('/home/marz/staffbot/api/auto_skills.txt', 'w') as f:
    f.write(out)

print(f"\nWritten to auto_skills.txt ({len(out)} chars)")
