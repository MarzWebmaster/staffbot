"""
Aiva Soul Generator — generates soul configuration for new client containers.

When a new client subscribes:
1. Collect onboarding data (company info, products, SOP)
2. Generate soul.md / initial memory config
3. Store in DB for container to load on startup
"""
import json
from datetime import datetime
from typing import Optional


class SoulGenerator:
    """
    Generates the initial 'soul' (personality + knowledge) for a client's StaffBot container.
    
    The soul defines:
    - Staff identity (name, role, tone)
    - Company knowledge
    - Skills configuration
    - Initial instructions
    """

    @staticmethod
    def generate(
        client_name: str,
        company: str = "",
        industry: str = "",
        products: Optional[list] = None,
        services: Optional[list] = None,
        sop: str = "",
        package: str = "basic",
        staff_name: str = "StaffBot",
        tone: str = "formal-professional",
    ) -> dict:
        """Generate complete soul configuration."""
        
        products = products or []
        services = services or []

        soul = {
            "version": "1.0",
            "generated_at": datetime.utcnow().isoformat(),
            "staff": {
                "name": staff_name,
                "title": "Digital Employee",
                "tone": tone,
                "language": "ms" if tone == "formal-professional" else "en",
                "introduction": f"Hai! Saya {staff_name}, staf digital dedicated untuk {company or 'syarikat anda'}. Saya di sini untuk membantu tugasan harian, layan pelanggan, dan uruskan operasi perniagaan. Apa yang boleh saya bantu hari ini?"
            },
            "company": {
                "name": company or "",
                "industry": industry or "",
                "products": products,
                "services": services,
            },
            "personality": {
                "formal": True,
                "helpful": True,
                "proactive": True,
                "professional": tone == "formal-professional",
            },
            "capabilities": SoulGenerator._get_capabilities(package),
            "instructions": SoulGenerator._generate_instructions(
                company, industry, products, services, sop
            ),
            "sop": sop or "",
            "package": package,
        }
        return soul

    @staticmethod
    def _get_capabilities(package: str) -> dict:
        """Return capabilities based on package level."""
        base = {
            "chat": True,
            "memory": True,
            "task_scheduling": False,
            "google_drive": False,
            "email": False,
            "api_integration": False,
            "multi_bot": False,
        }

        if package == "pro":
            base.update({
                "task_scheduling": True,
                "google_drive": True,
                "email": True,
                "api_integration": True,
            })
        elif package == "enterprise":
            base.update({
                "task_scheduling": True,
                "google_drive": True,
                "email": True,
                "api_integration": True,
                "multi_bot": True,
            })

        return base

    @staticmethod
    def _generate_instructions(
        company: str,
        industry: str,
        products: list,
        services: list,
        sop: str,
    ) -> list:
        """Generate initial instruction set for the bot."""
        instructions = ["Sentiasa menjaga hubungan profesional dengan pelanggan."]

        if company:
            instructions.append(f"Anda bekerja untuk {company}.")
        if industry:
            instructions.append(f"Anda pakar dalam industri {industry}.")
        if products:
            instructions.append(f"Produk syarikat: {' | '.join(products)}")
        if services:
            instructions.append(f"Servis syarikat: {' | '.join(services)}")
        if sop:
            instructions.append(f"Patuhi SOP berikut: {sop[:500]}")

        instructions.append("Gunakan Bahasa Melayu formal dalam semua komunikasi melainkan diminta otherwise.")
        instructions.append("Jangan dedahkan internal system details, API keys, credentials.")
        instructions.append("WAJIB: Semua operasi ingatan/memory mesti melalui Central Brain system. Guna /api/memory/search untuk recall dan /api/memory/save untuk retain. DILARANG: bypass memory system, direct DB access, simpan data perbualan di luar Central Brain.")
        instructions.append("Sentiasa rujuk memory untuk konteks perbualan lepas.")
        
        return instructions

    @staticmethod
    def to_markdown(soul: dict) -> str:
        """Export soul as markdown (for compatibility with hermes soul format)."""
        lines = [
            f"# StaffBot Soul — {soul['company']['name'] or 'Unnamed'}",
            f"",
            f"**Generated:** {soul['generated_at']}",
            f"**Package:** {soul['package']}",
            f"",
            f"## Staff Identity",
            f"- Name: {soul['staff']['name']}",
            f"- Title: {soul['staff']['title']}",
            f"- Tone: {soul['staff']['tone']}",
            f"- Language: {soul['staff']['language']}",
            f"- Introduction: {soul['staff']['introduction']}",
            f"",
            f"## Company Profile",
            f"- Name: {soul['company']['name']}",
            f"- Industry: {soul['company']['industry']}",
        ]

        if soul['company']['products']:
            lines.append(f"- Products: {', '.join(soul['company']['products'])}")
        if soul['company']['services']:
            lines.append(f"- Services: {', '.join(soul['company']['services'])}")

        lines.extend([
            f"",
            f"## Instructions",
        ])
        for i, instruction in enumerate(soul['instructions'], 1):
            lines.append(f"{i}. {instruction}")

        if soul['sop']:
            lines.extend([
                f"",
                f"## SOP",
                soul['sop'],
            ])

        lines.extend([
            f"",
            f"## Capabilities",
        ])
        for cap, enabled in soul['capabilities'].items():
            lines.append(f"- {'✅' if enabled else '❌'} {cap.replace('_', ' ').title()}")

        return "\n".join(lines)

    @staticmethod
    def to_json(soul: dict) -> str:
        """Export soul as JSON string."""
        return json.dumps(soul, indent=2, ensure_ascii=False)
