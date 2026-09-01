"""
Import real Polluxa CRM outreach export into PostgreSQL Star Schema.
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select, text
from src.logging_config import setup_logging
from src.models import get_session, init_db
from src.models.dimensions import DimAgent, DimLead, DimCampaign, DimAccountTier, DimDate
from src.models.facts import FactOutreachEvent, FactDailyAgentActivity

def parse_datetime(val: str | None) -> datetime | None:
    if not val or not val.strip():
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def import_real_crm_data(csv_path: str = "data/newton-leads-all-110-2026-08-31.csv") -> None:
    setup_logging()
    init_db()
    session = get_session()

    agent_name = "Bhavana B Srivatsa"
    agent_id = "bhavana_b_srivatsa"

    # 1. Ensure Agent exists with Tier 5 (1+ Year / Minimal Risk)
    agent = session.execute(
        select(DimAgent).where(DimAgent.agent_id == agent_id, DimAgent.is_current == True)
    ).scalar_one_or_none()

    if not agent:
        agent = DimAgent(
            agent_id=agent_id,
            display_name=agent_name,
            linkedin_email="bhavana.srivatsa@linkedin.com",
            status="active",
            tier_key=5,  # 1+ Year (Minimal Risk)
            is_current=True,
        )
        session.add(agent)
        session.flush()

    agent_key = agent.agent_key

    # 2. Ensure Campaign exists
    camp_id = "camp_tech_recruiters"
    campaign = session.execute(
        select(DimCampaign).where(DimCampaign.campaign_id == camp_id)
    ).scalar_one_or_none()

    if not campaign:
        campaign = DimCampaign(
            campaign_id=camp_id,
            campaign_name="Technical Recruiters Outreach",
            campaign_type="LINKEDIN_AUTOMATION",
            target_segment="Technical Recruiters",
            created_at=datetime.now(timezone.utc),
        )
        session.add(campaign)
        session.flush()

    campaign_key = campaign.campaign_key

    # 3. Resolve CSV file path
    filepath = Path(csv_path)
    if not filepath.exists():
        fallback_path = Path("data/polluxa_crm_export.csv")
        if fallback_path.exists():
            filepath = fallback_path
        else:
            raise FileNotFoundError(f"Neither {filepath} nor {fallback_path} could be found.")

    leads_loaded = 0
    leads_updated = 0
    events_loaded = 0

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Flexible field extraction (handles both Newton and standard Polluxa export columns)
            name = (row.get("Name") or row.get("name") or "Unknown Lead").strip()
            job_title = (row.get("Job Title") or row.get("job_title") or "").strip()
            company = (row.get("Company") or row.get("company") or "").strip()
            location = (row.get("Location") or row.get("location") or "").strip()
            industry = (row.get("Industry") or row.get("industry") or "").strip()
            status_raw = (row.get("SDR Status") or row.get("status") or "captured").strip().lower()
            url = (row.get("LinkedIn URL") or row.get("linkedin_url") or "").strip()
            
            sent_at_str = (row.get("Invite Sent At") or row.get("sent_at") or "").strip()
            connected_at_str = (row.get("Connected At") or row.get("accepted_at") or "").strip()
            added_on_str = (row.get("Added On") or "").strip()

            clean_id_name = "".join(c if c.isalnum() else "_" for c in name.lower())
            if url:
                slug = url.rstrip("/").split("/")[-1]
                lead_id = f"lead_{slug}"
            else:
                lead_id = f"lead_{clean_id_name}"

            # Standardize lead status
            if "connect" in status_raw:
                lead_status = "CONNECTED"
            elif "invite" in status_raw or "sent" in status_raw:
                lead_status = "INVITE_SENT"
            elif "enrich" in status_raw:
                lead_status = "ENRICHED"
            else:
                lead_status = "CAPTURED"

            segment_val = industry if industry else (location if location else "General")

            # Upsert Lead into dim_lead
            lead = session.execute(
                select(DimLead).where(DimLead.lead_id == lead_id, DimLead.is_current == True)
            ).scalar_one_or_none()

            if not lead:
                lead = DimLead(
                    lead_id=lead_id,
                    full_name=name,
                    company=company if company else "Confidential",
                    title=job_title if job_title else "Recruiter",
                    linkedin_url=url,
                    segment=segment_val,
                    lead_status=lead_status,
                    is_current=True,
                )
                session.add(lead)
                session.flush()
                leads_loaded += 1
            else:
                # Update existing lead metadata if newer info available
                if company and lead.company in ("Confidential", ""):
                    lead.company = company
                if job_title and lead.title in ("Recruiter", ""):
                    lead.title = job_title
                lead.lead_status = lead_status
                leads_updated += 1

            lead_key = lead.lead_key

            # Parse datetime fields
            sent_dt = parse_datetime(sent_at_str)
            connected_dt = parse_datetime(connected_at_str)
            added_dt = parse_datetime(added_on_str)

            # 1. INVITE_SENT Event (if sent)
            if sent_dt or "invite" in status_raw or "connect" in status_raw:
                evt_dt = sent_dt or added_dt or datetime.now(timezone.utc)
                sent_date_key = int(evt_dt.strftime("%Y%m%d"))
                sent_evt_id = f"evt_sent_{lead_id}"

                existing_sent = session.execute(
                    select(FactOutreachEvent).where(FactOutreachEvent.event_source_id == sent_evt_id)
                ).scalar_one_or_none()

                if not existing_sent:
                    evt_sent = FactOutreachEvent(
                        event_source_id=sent_evt_id,
                        agent_key=agent_key,
                        lead_key=lead_key,
                        campaign_key=campaign_key,
                        date_key=sent_date_key,
                        event_type="INVITE_SENT",
                        event_timestamp=evt_dt,
                        event_status="SUCCESS",
                    )
                    session.add(evt_sent)
                    events_loaded += 1

            # 2. ACCEPTED Event (if connected)
            if (connected_dt or "connect" in status_raw) and ("connect" in status_raw or connected_dt):
                acc_dt = connected_dt or datetime.now(timezone.utc)
                acc_date_key = int(acc_dt.strftime("%Y%m%d"))
                acc_evt_id = f"evt_acc_{lead_id}"
                
                resp_time_mins = None
                if sent_dt and acc_dt >= sent_dt:
                    resp_time_mins = int((acc_dt - sent_dt).total_seconds() / 60)

                existing_acc = session.execute(
                    select(FactOutreachEvent).where(FactOutreachEvent.event_source_id == acc_evt_id)
                ).scalar_one_or_none()

                if not existing_acc:
                    evt_acc = FactOutreachEvent(
                        event_source_id=acc_evt_id,
                        agent_key=agent_key,
                        lead_key=lead_key,
                        campaign_key=campaign_key,
                        date_key=acc_date_key,
                        event_type="ACCEPTED",
                        event_timestamp=acc_dt,
                        event_status="SUCCESS",
                        response_time_minutes=resp_time_mins,
                    )
                    session.add(evt_acc)
                    events_loaded += 1

    session.commit()
    print(f"✓ Successfully imported real Polluxa / Newton CRM data from {filepath.name}:")
    print(f"  • Agent: {agent_name} (Tier: 1+ Year / Minimal Risk)")
    print(f"  • New Leads Added: {leads_loaded}")
    print(f"  • Leads Updated: {leads_updated}")
    print(f"  • Outreach Events Added: {events_loaded}")
    session.close()

if __name__ == "__main__":
    target_csv = sys.argv[1] if len(sys.argv) > 1 else "data/newton-leads-all-110-2026-08-31.csv"
    import_real_crm_data(target_csv)
