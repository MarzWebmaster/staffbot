import re

with open('/root/staffbot/api/app/routers/admin/policy.py', 'r') as f:
    content = f.read()

CATEGORY_MAP = {
    'security': '🛡 Cybersecurity', 'hermes-red-teaming': '🛡 Cybersecurity', 'hub-red-teaming': '🛡 Cybersecurity',
    'aiml': '🤖 AI & Automation', 'automation': '🤖 AI & Automation',
    'autonomous-ai-agents': '🤖 AI & Automation', 'hermes-autonomous-ai-agents': '🤖 AI & Automation',
    'hub-autonomous-ai-agents': '🤖 AI & Automation', 'mlops': '🤖 AI & Automation',
    'hermes-mlops': '🤖 AI & Automation', 'hub-mlops': '🤖 AI & Automation',
    'hermes-inference': '🤖 AI & Automation', 'hermes-models': '🤖 AI & Automation', 'hermes-evaluation': '🤖 AI & Automation',
    'creative-design': '🎨 Design & Media', 'creative': '🎨 Design & Media',
    'hermes-creative': '🎨 Design & Media', 'hub-creative': '🎨 Design & Media',
    'hermes-media': '🎨 Design & Media', 'hub-media': '🎨 Design & Media', 'branding': '🎨 Design & Media',
    'devops': '☁️ DevOps & Infra', 'dev-infra': '☁️ DevOps & Infra',
    'hermes-devops': '☁️ DevOps & Infra', 'hub-devops': '☁️ DevOps & Infra',
    'system': '☁️ DevOps & Infra', 'integration': '☁️ DevOps & Infra', 'integrations': '☁️ DevOps & Infra',
    'migration': '☁️ DevOps & Infra', 'technical': '☁️ DevOps & Infra',
    'mcp': '☁️ DevOps & Infra', 'hermes-mcp': '☁️ DevOps & Infra', 'hub-mcp': '☁️ DevOps & Infra',
    'local': '☁️ DevOps & Infra', 'blockchain': '☁️ DevOps & Infra',
    'hermes-smart-home': '☁️ DevOps & Infra', 'hub-smart-home': '☁️ DevOps & Infra',
    'research': '📊 Data & Research', 'hermes-research': '📊 Data & Research', 'hub-research': '📊 Data & Research',
    'business-intelligence': '📊 Data & Research', 'hermes-data-science': '📊 Data & Research', 'hub-data-science': '📊 Data & Research',
    'software-development': '🌐 Web & Development', 'web-development': '🌐 Web & Development',
    'hermes-software-development': '🌐 Web & Development', 'hub-software-development': '🌐 Web & Development',
    'hermes-github': '🌐 Web & Development', 'hub-github': '🌐 Web & Development',
    'productivity': '📋 Productivity', 'hermes-productivity': '📋 Productivity',
    'hub-productivity': '📋 Productivity', 'documents': '📋 Productivity',
    'hermes-note-taking': '📋 Productivity', 'hub-note-taking': '📋 Productivity',
    'marketing': '📈 Marketing & Sales', 'sales': '📈 Marketing & Sales',
    'sales-marketing': '📈 Marketing & Sales', 'hub-business-development': '📈 Marketing & Sales',
    'hermes-social-media': '📈 Marketing & Sales', 'hub-social-media': '📈 Marketing & Sales',
    'entrepreneurship': '📈 Marketing & Sales', 'economy': '📈 Marketing & Sales', 'ecommerce': '📈 Marketing & Sales',
    'communication': '💬 Communication', 'messaging': '💬 Communication',
    'hermes-email': '💬 Communication', 'hub-email': '💬 Communication', 'email': '💬 Communication',
    'finance': '💰 Finance & Accounting', 'accounting': '💰 Finance & Accounting',
    'knowledge': '📝 Content Writing',
    'governance': '⚖️ Legal & Compliance',
    'hermes-apple': '🍎 Apple Ecosystem', 'hub-apple': '🍎 Apple Ecosystem',
    'hermes-gaming': '🎮 Gaming', 'hub-gaming': '🎮 Gaming',
    'operations': '🔧 Technical Support', 'customer-support': '🔧 Technical Support',
    'management': '🔧 Technical Support', 'hermes-skills': '🔧 Technical Support',
    'dogfood': '🔧 Technical Support', 'technology': '🔧 Technical Support',
    'industry': '🔧 Technical Support', 'hr': '🔧 Technical Support',
    'manufacturing': '🔧 Technical Support', 'healthcare': '🔧 Technical Support',
    'education': '🔧 Technical Support', 'construction': '🔧 Technical Support',
    'hospitality': '🔧 Technical Support', 'real-estate': '🔧 Technical Support',
    'logistics': '🔧 Technical Support', 'agriculture': '🔧 Technical Support', 'health': '🔧 Technical Support',
}

start = content.find('BUILTIN_SKILLS = [')
end = content.find('BUILTIN_TOOLSETS = [')
section = content[start:end]

idx = 0
count = 0
with open('/root/staffbot/merge_skills.sql', 'w') as out:
    while idx < len(section):
        bs = section.find('{', idx)
        if bs == -1: break
        depth = 1; be = bs + 1
        while depth > 0 and be < len(section):
            if section[be] == '{': depth += 1
            elif section[be] == '}': depth -= 1
            be += 1
        raw = section[bs:be]
        id_m = re.search(r'"id":\s*"([^"]+)"', raw)
        name_m = re.search(r'"name":\s*"([^"]+)"', raw)
        cat_m = re.search(r'"category":\s*"([^"]+)"', raw)
        desc_m = re.search(r'"desc":\s*"([^"]+)"', raw)
        if id_m:
            sid = id_m.group(1)
            name = (name_m.group(1) if name_m else sid).replace("'", "''")
            desc = (desc_m.group(1) if desc_m else '').replace("'", "''")
            cat = cat_m.group(1) if cat_m else ''
            dc = CATEGORY_MAP.get(cat, cat)
            out.write(f"INSERT INTO skills_registry (name, description, category, display_category, tags) VALUES ('{sid}','{desc}','{cat}','{dc}',ARRAY['builtin']) ON CONFLICT (name) DO UPDATE SET display_category=EXCLUDED.display_category, description=EXCLUDED.description, category=EXCLUDED.category;\n")
            count += 1
        idx = be
    out.write(f"-- Total: {count} BUILTIN skills\n")

print(f"Generated {count} INSERTs")
