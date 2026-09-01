"""
LinkedIn Official Data Archive Importer.

Parses and ingests real personal LinkedIn data exports:
  - Connections.csv: Real 1st-degree connections → dim_lead + fact_outreach_event (ACCEPTED)
  - Invitations.csv: Real sent/received invitations → fact_outreach_event (INVITE_SENT)
  - messages.csv: Real direct messages & replies → fact_outreach_event (MESSAGE_SENT / REPLY_RECEIVED)
"""

from __future__ import annotations

import csv
import io
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
import structlog

from src.models import get_session, init_db
from src.models.dimensions import DimAgent, DimLead, DimCampaign, DimDate
from src.models.facts import FactOutreachEvent, FactDailyAgentActivity
from src.pipeline.loader import DataLoader

logger = structlog.get_logger(__name__)


def parse_linkedin_date(date_str: str) -> datetime | None:
    """Parse various date formats found in LinkedIn CSV exports."""
    if not date_str or not date_str.strip():
        return None

    date_str = date_str.strip()
    formats = [
        "%d %b %Y",          # 15 Aug 2024
        "%d-%b-%y",          # 15-Aug-24
        "%Y-%m-%d",          # 2024-08-15
        "%m/%d/%Y",          # 08/15/2024
        "%m/%d/%y",          # 08/15/24
        "%Y-%m-%d %H:%M:%S", # 2024-08-15 14:30:00
        "%m/%d/%Y %I:%M:%S %p", # 08/15/2024 02:30:00 PM
        "%Y-%m-%dT%H:%M:%SZ", # ISO
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class LinkedInArchiveImporter:
    """Imports official personal LinkedIn data export files into PostgreSQL Star Schema."""

    def __init__(self, agent_display_name: str = "My LinkedIn Account"):
        self.session = get_session()
        self.loader = DataLoader(self.session)
        self.agent_display_name = agent_display_name
        self.agent_key: int | None = None
        self.campaign_key: int | None = None

    def _ensure_agent_and_campaign(self) -> tuple[int, int]:
        """Ensure default agent and personal campaign exist in dimensions."""
        # Find or create agent
        agent = self.session.execute(
            select(DimAgent).where(DimAgent.display_name == self.agent_display_name, DimAgent.is_current == True)
        ).scalar_one_or_none()

        if not agent:
            agent = DimAgent(
                agent_id="my_live_account",
                display_name=self.agent_display_name,
                status="active",
                tier_key=5,  # 1+ Year (Minimal Risk)
                is_current=True,
            )
            self.session.add(agent)
            self.session.commit()

        self.agent_key = agent.agent_key

        # Find or create campaign
        campaign = self.session.execute(
            select(DimCampaign).where(DimCampaign.campaign_name == "Personal LinkedIn Network")
        ).scalar_one_or_none()

        if not campaign:
            campaign = DimCampaign(
                campaign_id="camp_personal_network",
                campaign_name="Personal LinkedIn Network",
                campaign_type="ORGANIC_NETWORK",
                target_segment="Professional Network",
                is_active=True,
            )
            self.session.add(campaign)
            self.session.commit()

        self.campaign_key = campaign.campaign_key
        return self.agent_key, self.campaign_key

    def import_connections(self, csv_filepath: str | Path) -> dict[str, int]:
        """
        Import real LinkedIn Connections.csv archive file.
        Populates dim_lead and fact_outreach_event (ACCEPTED).
        """
        self._ensure_agent_and_campaign()
        filepath = Path(csv_filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        # LinkedIn CSV files often have 2-4 introductory comment lines before the header
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        header_idx = 0
        for i, line in enumerate(lines):
            if "First Name" in line or "First name" in line or "URL" in line:
                header_idx = i
                break

        reader = csv.DictReader(lines[header_idx:])
        leads_added = 0
        events_added = 0

        for idx, row in enumerate(reader):
            first_name = (row.get("First Name") or row.get("First name") or "").strip()
            last_name = (row.get("Last Name") or row.get("Last name") or "").strip()
            if not first_name and not last_name:
                continue

            full_name = f"{first_name} {last_name}".strip()
            job_title = (row.get("Position") or row.get("Job Title") or "Professional").strip()
            company = (row.get("Company") or row.get("Organization") or "Self-Employed").strip()
            url = (row.get("URL") or row.get("Profile URL") or f"https://linkedin.com/in/{first_name.lower()}-{last_name.lower()}").strip()
            email = (row.get("Email Address") or row.get("Email") or None)
            connected_on_raw = (row.get("Connected On") or row.get("Connected on") or "")
            connected_at = parse_linkedin_date(connected_on_raw) or datetime.now(timezone.utc)

            lead_id = f"real_lead_{abs(hash(url)) % 10000000}"

            # Upsert into dim_lead
            lead = self.session.execute(
                select(DimLead).where(DimLead.lead_id == lead_id, DimLead.is_current == True)
            ).scalar_one_or_none()

            if not lead:
                lead = DimLead(
                    lead_id=lead_id,
                    first_name=first_name,
                    last_name=last_name,
                    company=company,
                    job_title=job_title,
                    linkedin_url=url,
                    email=email,
                    target_segment="1st Degree Connections",
                    status="CONNECTED",
                    is_current=True,
                )
                self.session.add(lead)
                self.session.flush()
                leads_added += 1

            # Lookup date_key
            date_key = int(connected_at.strftime("%Y%m%d"))

            # Create ACCEPTED event in fact_outreach_event
            event_id = f"evt_conn_{lead_id}"
            existing_event = self.session.execute(
                select(FactOutreachEvent).where(FactOutreachEvent.event_source_id == event_id)
            ).scalar_one_or_none()

            if not existing_event:
                event = FactOutreachEvent(
                    event_source_id=event_id,
                    agent_key=self.agent_key,
                    lead_key=lead.lead_key,
                    campaign_key=self.campaign_key,
                    date_key=date_key,
                    event_type="ACCEPTED",
                    event_timestamp=connected_at,
                    event_status="SUCCESS",
                )
                self.session.add(event)
                events_added += 1

        self.session.commit()
        logger.info(
            "linkedin_connections_imported",
            leads_added=leads_added,
            events_added=events_added,
            source_file=str(filepath),
        )
        return {"leads_added": leads_added, "events_added": events_added}

    def import_invitations(self, csv_filepath: str | Path) -> dict[str, int]:
        """
        Import real LinkedIn Invitations.csv archive file.
        Populates fact_outreach_event (INVITE_SENT).
        """
        self._ensure_agent_and_campaign()
        filepath = Path(csv_filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        header_idx = 0
        for i, line in enumerate(lines):
            if "From" in line or "To" in line or "Sent At" in line:
                header_idx = i
                break

        reader = csv.DictReader(lines[header_idx:])
        invites_added = 0

        for row in reader:
            to_person = (row.get("To") or "").strip()
            direction = (row.get("Direction") or "OUTGOING").strip().upper()
            sent_at_raw = (row.get("Sent At") or row.get("sent_at") or "")
            sent_at = parse_linkedin_date(sent_at_raw) or datetime.now(timezone.utc)

            if "OUTGOING" not in direction and direction != "OUTGOING":
                continue  # Only count invites sent by agent

            event_id = f"evt_inv_{abs(hash(to_person + str(sent_at))) % 10000000}"
            date_key = int(sent_at.strftime("%Y%m%d"))

            existing = self.session.execute(
                select(FactOutreachEvent).where(FactOutreachEvent.event_source_id == event_id)
            ).scalar_one_or_none()

            if not existing:
                event = FactOutreachEvent(
                    event_source_id=event_id,
                    agent_key=self.agent_key,
                    lead_key=None,
                    campaign_key=self.campaign_key,
                    date_key=date_key,
                    event_type="INVITE_SENT",
                    event_timestamp=sent_at,
                    event_status="SUCCESS",
                )
                self.session.add(event)
                invites_added += 1

        self.session.commit()
        logger.info("linkedin_invitations_imported", invites_added=invites_added)
        return {"invites_added": invites_added}
