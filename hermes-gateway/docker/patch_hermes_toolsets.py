#!/usr/bin/env python3
"""Properly insert staffbot toolset into Hermes Agent source files."""
import re

# ── Patch toolsets.py ────────────────────────────────────────────────
toolsets_path = "/opt/hermes-agent/toolsets.py"
with open(toolsets_path, 'r') as f:
    content = f.read()

# Check if already properly patched
if '"staffbot": {' in content and '"computer_use": {' in content:
    # Check if computer_use is intact (not corrupted)
    if '        "includes": []\n    },' in content:
        print("toolsets.py already properly patched.")
    else:
        print("toolsets.py corrupted — restoring from backup logic...")
        # The file is corrupted, we need to fix it
        # Remove the corrupted staffbot block
        content = re.sub(
            r'"includes": \[\](.*?)"staffbot".*?"includes": \[\]\s*\}',
            '"includes": []\n    },',
            content,
            flags=re.DOTALL
        )
        print("Fixed corruption in toolsets.py")
else:
    # Insert staffbot after computer_use block
    old_block = '''    "computer_use": {
        "description": (
            "Background macOS desktop control via cua-driver — screenshots, "
            "mouse, keyboard, scroll, drag. Does NOT steal the user's cursor "
            "or keyboard focus. Works with any tool-capable model."
        ),
        "tools": ["computer_use"],
        "includes": []
    },'''
    
    new_block = '''    "computer_use": {
        "description": (
            "Background macOS desktop control via cua-driver — screenshots, "
            "mouse, keyboard, scroll, drag. Does NOT steal the user's cursor "
            "or keyboard focus. Works with any tool-capable model."
        ),
        "tools": ["computer_use"],
        "includes": []
    },

    "staffbot": {
        "description": "StaffBot.my tasks, upload & link extraction tools",
        "tools": ["create_task", "list_tasks", "update_task", "delete_task",
                  "task_stats", "upload_document", "extract_link"],
        "includes": []
    },'''
    
    if old_block in content:
        content = content.replace(old_block, new_block)
        print("Inserted staffbot into toolsets.py TOOLSETS")
    else:
        print("WARNING: Could not find computer_use block in toolsets.py!")

with open(toolsets_path, 'w') as f:
    f.write(content)

# ── Patch tools_config.py ────────────────────────────────────────────
tools_config_path = "/opt/hermes-agent/hermes_cli/tools_config.py"
with open(tools_config_path, 'r') as f:
    content = f.read()

if '("staffbot"' in content:
    print("tools_config.py already patched.")
else:
    old_line = '    ("computer_use",     "🖱️  Computer Use (macOS)",     "background desktop control via cua-driver"),'
    new_lines = '''    ("computer_use",     "🖱️  Computer Use (macOS)",     "background desktop control via cua-driver"),
    ("staffbot",       "🤖 StaffBot Tasks & Upload",    "create_task, list_tasks, update_task, delete_task, task_stats, upload_document, extract_link"),'''
    
    if old_line in content:
        content = content.replace(old_line, new_lines)
        print("Inserted staffbot into tools_config.py CONFIGURABLE_TOOLSETS")
    else:
        print("WARNING: Could not find computer_use line in tools_config.py!")

with open(tools_config_path, 'w') as f:
    f.write(content)

# ── Verify ────────────────────────────────────────────────────────────
# Quick syntax check
try:
    with open(toolsets_path, 'r') as f:
        compile(f.read(), toolsets_path, 'exec')
    print("✅ toolsets.py compiles OK")
except SyntaxError as e:
    print(f"❌ toolsets.py SyntaxError: {e}")

try:
    with open(tools_config_path, 'r') as f:
        compile(f.read(), tools_config_path, 'exec')
    print("✅ tools_config.py compiles OK")
except SyntaxError as e:
    print(f"❌ tools_config.py SyntaxError: {e}")

print("\nDone.")
