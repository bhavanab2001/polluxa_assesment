"""
Sample data generator for development, testing, and live demos.

Generates realistic LinkedIn outreach data including:
- 3 agents with different tiers
- 2 campaigns
- 50+ leads
- 500+ outreach events over 30 days
- Includes deliberate anomalies for risk model testing
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure import directory exists
DATA_DIR = PROJECT_ROOT / "data" / "imports"


def _random_name() -> str:
    """Generate a random realistic name."""
    first_names = [
        "Sarah", "James", "Priya", "Michael", "Aisha", "David", "Emma",
        "Carlos", "Yuki", "Oliver", "Fatima", "Alex", "Nina", "Raj",
        "Sophie", "Liam", "Mei", "Daniel", "Ana", "Thomas",
    ]
    last_names = [
        "Johnson", "Patel", "Williams", "Kumar", "Brown", "Chen",
        "Garcia", "Kim", "Anderson", "Singh", "Taylor", "Nguyen",
        "Martinez", "Lee", "Wilson", "Tanaka", "Robinson", "Ali",
    ]
    return f"{random.choice(first_names)} {random.choice(last_names)}"


def _random_company() -> str:
    """Generate a random company name."""
    companies = [
        "TechCorp Global", "InnovateSoft", "DataDriven Inc", "CloudScale",
        "NextGen Solutions", "FinTech Pro", "AI Dynamics", "GrowthLab",
        "SaaS Masters", "Digital First", "Enterprise Logic", "ScaleUp HQ",
        "RevOps Co", "PipelineAI", "SmartReach", "LeadGen Plus",
        "B2B Connect", "SalesForce Pro", "MarketEdge", "CRM Innovators",
    ]
    return random.choice(companies)


def _random_title() -> str:
    """Generate a random job title."""
    titles = [
        "VP of Sales", "Head of Marketing", "CTO", "CEO", "COO",
        "Director of Engineering", "Product Manager", "Sales Manager",
        "Growth Lead", "Business Development Manager", "CMO",
        "Head of Partnerships", "Director of Revenue", "Founder",
        "VP of Engineering", "Senior Account Executive",
    ]
    return random.choice(titles)


def generate_sample_data() -> None:
    """Generate all sample CSV files for the pipeline."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    agents = _generate_agents()
    leads = _generate_leads(50)
    campaigns = _generate_campaigns()
    templates = _generate_templates()
    events = _generate_events(agents, leads, campaigns, templates, days=30)

    _write_json(DATA_DIR / "agents.json", agents)
    _write_json(DATA_DIR / "leads.json", leads)
    _write_json(DATA_DIR / "campaigns.json", campaigns)
    _write_json(DATA_DIR / "templates.json", templates)
    _write_json(DATA_DIR / "events.json", events)

    print(f"Generated: {len(agents)} agents, {len(leads)} leads, "
          f"{len(campaigns)} campaigns, {len(templates)} templates, "
          f"{len(events)} events")
    print(f"Files written to: {DATA_DIR.absolute()}")


def _generate_agents() -> list[dict[str, Any]]:
    """Generate 3 agents with different tiers."""
    return [
        {
            "id": "agent_001",
            "name": "Sales Agent Alpha",
            "email": "alpha@example.com",
            "status": "active",
            "account_age": "6-12 Months",
        },
        {
            "id": "agent_002",
            "name": "Sales Agent Beta",
            "email": "beta@example.com",
            "status": "active",
            "account_age": "2-6 Months",
        },
        {
            "id": "agent_003",
            "name": "Sales Agent Gamma",
            "email": "gamma@example.com",
            "status": "paused",
            "account_age": "1+ Year",
        },
    ]


def _generate_leads(count: int) -> list[dict[str, Any]]:
    """Generate realistic lead records."""
    segments = ["Tech Founders", "Sales Leaders", "Marketing Executives", "Engineering VPs"]
    statuses = ["new", "contacted", "connected", "replied", "qualified", "meeting_booked"]

    leads = []
    for i in range(count):
        leads.append({
            "id": f"lead_{i + 1:04d}",
            "name": _random_name(),
            "company": _random_company(),
            "title": _random_title(),
            "linkedin_url": f"https://linkedin.com/in/lead-{i + 1}",
            "segment": random.choice(segments),
            "status": random.choice(statuses),
        })
    return leads


def _generate_campaigns() -> list[dict[str, Any]]:
    """Generate 2 outreach campaigns."""
    return [
        {
            "id": "camp_001",
            "name": "Q3 Tech Founders Outreach",
            "type": "connection_request",
            "segment": "Tech Founders",
            "created_at": "2026-07-01T00:00:00Z",
        },
        {
            "id": "camp_002",
            "name": "Sales Leaders Network Build",
            "type": "inmail",
            "segment": "Sales Leaders",
            "created_at": "2026-07-15T00:00:00Z",
        },
    ]


def _generate_templates() -> list[dict[str, Any]]:
    """Generate message templates."""
    return [
        {
            "id": "tmpl_001",
            "name": "Initial Connection - Tech",
            "body": "Hi {{first_name}}, I came across your work at {{company}} and would love to connect.",
            "channel": "linkedin",
        },
        {
            "id": "tmpl_002",
            "name": "Follow-up - Value Prop",
            "body": "Thanks for connecting, {{first_name}}! I wanted to share how we help {{industry}} leaders...",
            "channel": "linkedin",
        },
        {
            "id": "tmpl_003",
            "name": "Meeting Request",
            "body": "Hi {{first_name}}, would you be open to a 15-min call next week?",
            "channel": "linkedin",
        },
    ]


def _generate_events(
    agents: list[dict],
    leads: list[dict],
    campaigns: list[dict],
    templates: list[dict],
    days: int = 30,
) -> list[dict[str, Any]]:
    """
    Generate realistic outreach events over N days.

    Simulates a realistic funnel:
    - Invite Sent → ~35% Accepted → ~20% Replied → ~5% Meeting Booked
    - Includes deliberate anomalies on days 20-22 for Agent Alpha (acceptance collapse)
    """
    events: list[dict[str, Any]] = []
    event_id = 1
    base_date = datetime.now(timezone.utc) - timedelta(days=days)

    for day_offset in range(days):
        current_date = base_date + timedelta(days=day_offset)

        for agent in agents:
            if agent["status"] == "paused" and day_offset > 20:
                continue  # Paused agents stop sending

            # Determine daily volume based on tier
            tier_limits = {
                "< 1 Month": 5, "1 Month": 10, "2-6 Months": 15,
                "6-12 Months": 25, "1+ Year": 30,
            }
            max_invites = tier_limits.get(agent["account_age"], 15)

            # Random daily invites (60-90% of limit)
            daily_invites = random.randint(int(max_invites * 0.6), max_invites)

            # Select random leads for this day
            day_leads = random.sample(leads, min(daily_invites, len(leads)))
            campaign = random.choice(campaigns)
            template = random.choice(templates)

            for lead in day_leads:
                timestamp = current_date + timedelta(
                    hours=random.randint(8, 18),
                    minutes=random.randint(0, 59),
                )

                # INVITE_SENT
                events.append({
                    "id": f"evt_{event_id:06d}",
                    "agent_id": agent["id"],
                    "lead_id": lead["id"],
                    "campaign_id": campaign["id"],
                    "template_id": template["id"],
                    "event_type": "INVITE_SENT",
                    "timestamp": timestamp.isoformat(),
                    "status": "SUCCESS",
                })
                event_id += 1

                # ACCEPTED (with anomaly injection)
                if agent["id"] == "agent_001" and 19 <= day_offset <= 22:
                    # Anomaly: acceptance rate collapses to ~5%
                    accept_prob = 0.05
                else:
                    accept_prob = 0.35

                if random.random() < accept_prob:
                    accept_time = timestamp + timedelta(
                        hours=random.randint(1, 48),
                        minutes=random.randint(0, 59),
                    )
                    events.append({
                        "id": f"evt_{event_id:06d}",
                        "agent_id": agent["id"],
                        "lead_id": lead["id"],
                        "campaign_id": campaign["id"],
                        "event_type": "ACCEPTED",
                        "timestamp": accept_time.isoformat(),
                        "status": "SUCCESS",
                    })
                    event_id += 1

                    # REPLY_RECEIVED (~20% of accepted)
                    if random.random() < 0.20:
                        reply_time = accept_time + timedelta(
                            hours=random.randint(1, 72),
                            minutes=random.randint(0, 59),
                        )
                        response_minutes = int((reply_time - accept_time).total_seconds() / 60)
                        events.append({
                            "id": f"evt_{event_id:06d}",
                            "agent_id": agent["id"],
                            "lead_id": lead["id"],
                            "campaign_id": campaign["id"],
                            "event_type": "REPLY_RECEIVED",
                            "timestamp": reply_time.isoformat(),
                            "status": "SUCCESS",
                            "response_time_minutes": response_minutes,
                        })
                        event_id += 1

                        # MEETING_BOOKED (~25% of replies)
                        if random.random() < 0.25:
                            meeting_time = reply_time + timedelta(
                                hours=random.randint(2, 24),
                            )
                            events.append({
                                "id": f"evt_{event_id:06d}",
                                "agent_id": agent["id"],
                                "lead_id": lead["id"],
                                "campaign_id": campaign["id"],
                                "event_type": "MEETING_BOOKED",
                                "timestamp": meeting_time.isoformat(),
                                "status": "SUCCESS",
                            })
                            event_id += 1

    # Add some deliberately bad records for DQ testing
    events.append({
        "id": f"evt_{event_id:06d}",
        "agent_id": None,  # Missing agent
        "lead_id": "lead_0001",
        "event_type": "INVITE_SENT",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    event_id += 1

    events.append({
        "id": f"evt_{event_id:06d}",
        "agent_id": "agent_001",
        "lead_id": "lead_0001",
        "event_type": "UNKNOWN_TYPE",  # Invalid event type
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    event_id += 1

    events.append({
        "id": f"evt_{event_id:06d}",
        "agent_id": "agent_001",
        "lead_id": "lead_0001",
        "event_type": "INVITE_SENT",
        "timestamp": "not-a-date",  # Unparseable timestamp
    })

    return events


def _write_json(filepath: Path, data: list[dict]) -> None:
    """Write data to a JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  ✓ {filepath.name}: {len(data)} records")


if __name__ == "__main__":
    generate_sample_data()
