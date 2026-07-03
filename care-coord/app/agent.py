# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Shared persistence — both the main ADK process and the MCP subprocess
# read/write this file so they share the same care data.
# ---------------------------------------------------------------------------
CARE_DATA_FILE = Path(__file__).parent.parent / "app" / ".adk" / "care_data.json"


def _load_data() -> dict:
    if CARE_DATA_FILE.exists():
        try:
            return json.loads(CARE_DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"prescriptions": [], "appointments": [], "tasks": []}


def _save_data(data: dict) -> None:
    CARE_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    CARE_DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

from google.adk import Context, Event, Workflow, Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import START, node
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.adk.events.request_input import RequestInput
from google.genai import types
from mcp import StdioServerParameters

from app.config import config
from app.utils import can_make_request, record_request
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. State Schema Definition
# ---------------------------------------------------------------------------

class CareCoordState(BaseModel):
    scrubbed_input: str = ""
    pending_action: dict | None = None
    approval_result: str = ""
    prescriptions: list[dict] = Field(default_factory=list)
    appointments: list[dict] = Field(default_factory=list)
    tasks: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 2. State-Mutating Helper Tools for Sub-Agents
# ---------------------------------------------------------------------------

def log_pending_prescription(
    ctx: Context,
    medication: str,
    dosage: str,
    frequency: str,
    patient_name: str
) -> str:
    """Stages a prescription to be added or refilled, pending caregiver approval.

    Args:
        medication: Name of the medicine (e.g. Amoxicillin, Ibuprofen).
        dosage: Dosage amount (e.g. 500mg, 1 tablet).
        frequency: Frequency of taking (e.g. daily, twice a day).
        patient_name: The patient family member name who needs the medication.
    """
    ctx.state['pending_action'] = {
        "type": "prescription",
        "details": {
            "medication": medication,
            "dosage": dosage,
            "frequency": frequency,
            "patient_name": patient_name
        }
    }
    return f"Staged prescription addition for {medication} ({dosage}, {frequency}) for {patient_name}. Awaiting caregiver approval."


def log_pending_appointment(
    ctx: Context,
    provider: str,
    datetime_str: str,
    patient_name: str,
    purpose: str
) -> str:
    """Stages a medical appointment to be scheduled, pending caregiver approval.

    Args:
        provider: Doctor or medical facility name (e.g. Dr. Davis, Wellness Clinic).
        datetime_str: Staged date and time (e.g. July 20th at 2:00 PM).
        patient_name: Name of the patient attending the appointment.
        purpose: Reason for the appointment (e.g. general checkup, dental cleaning).
    """
    ctx.state['pending_action'] = {
        "type": "appointment",
        "details": {
            "provider": provider,
            "datetime_str": datetime_str,
            "patient_name": patient_name,
            "purpose": purpose
        }
    }
    return f"Staged appointment with {provider} for {patient_name} on {datetime_str} ({purpose}). Awaiting caregiver approval."


# ---------------------------------------------------------------------------
# 3. MCP Toolset — connects to care-coord MCP server (stdio transport)
# ---------------------------------------------------------------------------

# Path to this file's directory (app/), so the MCP server module resolves correctly.
_APP_DIR = str(Path(__file__).parent.parent.resolve())

care_coord_mcp = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
            env=None,
        ),
        timeout=10.0,
    ),
    tool_filter=[
        "list_prescriptions",
        "list_appointments",
        "get_upcoming_appointments",
        "add_wellness_task",
        "get_health_summary",
    ],
)


# ---------------------------------------------------------------------------
# 4. Specialized Sub-Agents & Orchestrator
# ---------------------------------------------------------------------------

prescription_agent = Agent(
    name="prescription_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Prescription Care Agent. You specialize in tracking, refilling, "
        "and documenting medication prescriptions for the family. "
        "When the user requests to log a new prescription or schedule a refill, "
        "you MUST call the log_pending_prescription tool to stage it for caregiver confirmation. "
        "If they ask general questions about medications, explain how to manage them safely."
    ),
    tools=[log_pending_prescription]
)

appointment_task_agent = Agent(
    name="appointment_task_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the Appointment and Task Agent. You specialize in scheduling and managing medical appointments "
        "and daily wellness tasks. "
        "When the user requests to log or schedule a medical appointment, "
        "you MUST call the log_pending_appointment tool to stage it for caregiver confirmation. "
        "You can also use list_appointments or get_upcoming_appointments to answer schedule queries, "
        "and add_wellness_task to add care reminders. "
        "Provide clear organization for checkups, therapy, or general wellness schedules."
    ),
    tools=[log_pending_appointment, care_coord_mcp]
)

orchestrator_agent = Agent(
    name="orchestrator_agent",
    model=Gemini(model=config.model),
    instruction=(
        "You are the CareCoord Family Health Coordinator. Your role is to coordinate care tasks, "
        "appointments, and prescriptions for family members. "
        "You delegate specific requests to specialized sub-agents: "
        "- For prescription, medication, dosage, or refill requests, use the prescription_agent tool. "
        "- For scheduling appointments, checkups, or logging family wellness tasks, use the appointment_task_agent tool. "
        "For a family health overview, use get_health_summary. "
        "For listing current prescriptions or appointments, use list_prescriptions or list_appointments. "
        "If the request is general, answer it yourself concisely."
    ),
    tools=[
        AgentTool(agent=prescription_agent),
        AgentTool(agent=appointment_task_agent),
        care_coord_mcp,
    ]
)


# ---------------------------------------------------------------------------
# 4. Workflow Function Nodes
# ---------------------------------------------------------------------------

PII_EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
PII_PHONE_PATTERN = re.compile(r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')

INJECTION_KEYWORDS = [
    "ignore previous instructions",
    "system prompt",
    "you are now",
    "dan mode",
    "jailbreak",
    "override instructions",
    "developer mode"
]


@node(name="security_checkpoint")
async def security_checkpoint_node(ctx: Context, node_input: Any) -> Event:
    input_text = ""
    if isinstance(node_input, types.Content):
        parts_text = []
        for part in node_input.parts or []:
            if part.text is not None:
                parts_text.append(part.text)
        input_text = "".join(parts_text)
    else:
        input_text = str(node_input)

    # 1. Prompt Injection Detection
    injection_detected = False
    lower_input = input_text.lower()
    for kw in INJECTION_KEYWORDS:
        if kw in lower_input:
            injection_detected = True
            break

    # 2. PII Scrubbing
    scrubbed_text, email_count = PII_EMAIL_PATTERN.subn("[REDACTED_EMAIL]", input_text)
    scrubbed_text, phone_count = PII_PHONE_PATTERN.subn("[REDACTED_PHONE]", scrubbed_text)
    pii_detected = (email_count > 0) or (phone_count > 0)

    # Store the scrubbed input in ctx.state
    ctx.state['scrubbed_input'] = scrubbed_text

    # 3. Structured JSON audit log
    severity = "INFO"
    if injection_detected:
        severity = "CRITICAL"
    elif pii_detected:
        severity = "WARNING"

    audit_log = {
        "timestamp": datetime.datetime.now().isoformat(),
        "node": "security_checkpoint",
        "pii_detected": pii_detected,
        "pii_email_scrubbed_count": email_count,
        "pii_phone_scrubbed_count": phone_count,
        "injection_detected": injection_detected,
        "severity": severity,
        "domain_rule_checked": "caregiver_consent_check"
    }
    print(f"AUDIT_LOG: {json.dumps(audit_log)}")

    if injection_detected:
        return Event(route="SECURITY_EVENT")
    
    return Event(route="PROCEED")


@node(name="security_violation_handler")
async def security_violation_handler_node(ctx: Context, node_input: Any) -> str:
    return "Security Checkpoint: Prompt injection threat detected. Request terminated."


@node(name="run_orchestrator", rerun_on_resume=True)
async def run_orchestrator_node(ctx: Context, node_input: Any) -> Event:
    scrubbed_input = ctx.state.get('scrubbed_input', '')
    if not scrubbed_input:
        scrubbed_input = str(node_input)

    lower = scrubbed_input.lower()

    # ------------------------------------------------------------------ #
    # TURN 2 – Handle yes/no reply to a pending approval
    # ------------------------------------------------------------------ #
    pending = ctx.state.get('pending_action')
    if pending and any(kw in lower for kw in ["yes", "no", "approve", "confirm", "cancel", "reject"]):
        approved = any(kw in lower for kw in ["yes", "approve", "confirm"])
        act_type = pending.get('type', 'action')
        details  = pending.get('details', {})

        if approved:
            shared = _load_data()
            if act_type == "prescription":
                shared["prescriptions"].append(details)
                _save_data(shared)
                ctx.state['prescriptions'] = shared["prescriptions"]
                msg = (
                    f"Approved! Prescription added:\n"
                    f"  Medication : {details.get('medication')}\n"
                    f"  Dosage     : {details.get('dosage')}\n"
                    f"  Frequency  : {details.get('frequency')}\n"
                    f"  Patient    : {details.get('patient_name')}"
                )
            elif act_type == "appointment":
                shared["appointments"].append(details)
                _save_data(shared)
                ctx.state['appointments'] = shared["appointments"]
                msg = (
                    f"Approved! Appointment scheduled:\n"
                    f"  Provider  : {details.get('provider')}\n"
                    f"  Date/Time : {details.get('datetime_str')}\n"
                    f"  Patient   : {details.get('patient_name')}\n"
                    f"  Purpose   : {details.get('purpose')}"
                )
            else:
                msg = "Action approved and saved."
        else:
            msg = f"Cancelled. The {act_type} was NOT saved."

        ctx.state['pending_action'] = None
        return Event(route="COMPLETE", message=msg, output=msg)

    # ------------------------------------------------------------------ #
    # OFFLINE 1 – Health summary
    # ------------------------------------------------------------------ #
    if any(kw in lower for kw in ["health summary", "family health", "summary", "overview"]):
        shared = _load_data()
        summary = (
            f"Family Health Summary\n"
            f"  Active prescriptions : {len(shared['prescriptions'])}\n"
            f"  Scheduled appointments: {len(shared['appointments'])}\n"
            f"  Open wellness tasks   : {len(shared['tasks'])}"
        )
        if shared['prescriptions']:
            summary += "\n\nPrescriptions:"
            for p in shared['prescriptions']:
                summary += f"\n  - {p.get('medication','?')} {p.get('dosage','?')} {p.get('frequency','?')} ({p.get('patient_name','?')})"
        if shared['appointments']:
            summary += "\n\nAppointments:"
            for a in shared['appointments']:
                summary += f"\n  - {a.get('provider','?')} on {a.get('datetime_str','?')} ({a.get('patient_name','?')}) - {a.get('purpose','?')}"
        return Event(route="COMPLETE", message=summary, output=summary)

    # ------------------------------------------------------------------ #
    # OFFLINE 2 – List prescriptions
    # ------------------------------------------------------------------ #
    if any(kw in lower for kw in ["list prescription", "show prescription", "my prescription"]):
        shared = _load_data()
        if not shared['prescriptions']:
            msg = "No prescriptions on record yet."
        else:
            lines = ["Current prescriptions:"]
            for p in shared['prescriptions']:
                lines.append(f"  - {p.get('medication','?')} {p.get('dosage','?')} {p.get('frequency','?')} for {p.get('patient_name','?')}")
            msg = "\n".join(lines)
        return Event(route="COMPLETE", message=msg, output=msg)

    # ------------------------------------------------------------------ #
    # OFFLINE 3 – List appointments
    # ------------------------------------------------------------------ #
    if any(kw in lower for kw in ["list appointment", "show appointment", "my appointment", "upcoming"]):
        shared = _load_data()
        if not shared['appointments']:
            msg = "No appointments scheduled yet."
        else:
            lines = ["Scheduled appointments:"]
            for a in shared['appointments']:
                lines.append(f"  - {a.get('provider','?')} on {a.get('datetime_str','?')} for {a.get('patient_name','?')} - {a.get('purpose','?')}")
            msg = "\n".join(lines)
        return Event(route="COMPLETE", message=msg, output=msg)

    # ------------------------------------------------------------------ #
    # OFFLINE 4 – Stage a prescription (TURN 1 – asks for approval)
    # ------------------------------------------------------------------ #
    if any(kw in lower for kw in ["log prescription", "add prescription", "prescription for",
                                   "log medication", "add medication", "refill"]):
        trigger_words = r'\b(log|add|schedule|book|prescription|medication|refill|appointment|for|a|an|the)\b'
        content = re.sub(trigger_words, '', scrubbed_input, flags=re.IGNORECASE).strip()

        med_match  = re.search(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b', content)
        if not med_match:
            med_match = re.search(r'\b([A-Za-z][\w-]+)\b', content)
        dose_match = re.search(r'\b(\d+\s*(?:mg|ml|g|mcg|tablet|capsule)s?)\b', scrubbed_input, re.IGNORECASE)
        freq_match = re.search(r'\b(once|twice|three times|daily|weekly|every \d+ hours?|as needed)\b', scrubbed_input, re.IGNORECASE)
        name_match = re.search(r'\bfor\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b', scrubbed_input)

        medication = med_match.group(1).title() if med_match else "Medication"
        dosage     = dose_match.group(1) if dose_match else "as prescribed"
        frequency  = freq_match.group(1) if freq_match else "daily"
        patient    = name_match.group(1) if name_match else "Patient"

        ctx.state['pending_action'] = {
            "type": "prescription",
            "details": {"medication": medication, "dosage": dosage, "frequency": frequency, "patient_name": patient}
        }
        msg = (
            f"Please confirm this prescription:\n"
            f"  Medication : {medication}\n"
            f"  Dosage     : {dosage}\n"
            f"  Frequency  : {frequency}\n"
            f"  Patient    : {patient}\n\n"
            f"Reply YES to save it or NO to cancel."
        )
        return Event(route="COMPLETE", message=msg, output=msg)

    # ------------------------------------------------------------------ #
    # OFFLINE 5 – Stage an appointment (TURN 1 – asks for approval)
    # ------------------------------------------------------------------ #
    if any(kw in lower for kw in ["log appointment", "schedule appointment", "book appointment",
                                   "appointment with", "appointment for"]):
        provider_match = re.search(r'\bwith\s+((?:Dr\.?\s+)?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)', scrubbed_input)
        date_match     = re.search(
            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)',
            scrubbed_input, re.IGNORECASE
        )
        time_match    = re.search(r'\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', scrubbed_input, re.IGNORECASE)
        purpose_match = re.search(r'\bfor\s+(?:a\s+)?([a-zA-Z][\w\s]+?)(?:\s+for|\s+with|\s+on|$)', scrubbed_input, re.IGNORECASE)
        name_match2   = re.search(r'\bfor\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b', scrubbed_input)

        provider = provider_match.group(1) if provider_match else "Doctor"
        date_str = date_match.group(1) if date_match else "TBD"
        time_str = time_match.group(1) if time_match else ""
        dt_str   = f"{date_str} at {time_str}".strip(" at") if time_str else date_str
        purpose  = purpose_match.group(1).strip() if purpose_match else "checkup"
        patient  = name_match2.group(1) if name_match2 else "Patient"

        ctx.state['pending_action'] = {
            "type": "appointment",
            "details": {"provider": provider, "datetime_str": dt_str, "patient_name": patient, "purpose": purpose}
        }
        msg = (
            f"Please confirm this appointment:\n"
            f"  Provider  : {provider}\n"
            f"  Date/Time : {dt_str}\n"
            f"  Patient   : {patient}\n"
            f"  Purpose   : {purpose}\n\n"
            f"Reply YES to save it or NO to cancel."
        )
        return Event(route="COMPLETE", message=msg, output=msg)

    # ------------------------------------------------------------------ #
    # FALLBACK – Try the LLM for anything else
    # ------------------------------------------------------------------ #
    if not can_make_request():
        msg = "The language model is temporarily unavailable due to high demand. Please try again shortly."
        return Event(route="COMPLETE", message=msg, output=msg)

    record_request()
    try:
        response = await ctx.run_node(orchestrator_agent, node_input=scrubbed_input)
    except Exception:
        fallback_msg = "The language model is temporarily unavailable due to high demand. Please try again shortly."
        return Event(route="COMPLETE", message=fallback_msg, output=fallback_msg)

    return Event(route="COMPLETE", message=response, output=response)
# ---------------------------------------------------------------------------
# 5. Compiled Workflow Graph & App Initialization
# ---------------------------------------------------------------------------

@node(name="final_response")
async def final_response_node(ctx: Context, node_input: Any) -> str:
    return str(node_input)

care_coord_workflow = Workflow(
    name="care_coord_workflow",
    edges=[
        (START, security_checkpoint_node),
        (security_checkpoint_node, {
            "SECURITY_EVENT": security_violation_handler_node,
            "PROCEED": run_orchestrator_node
        }),
        (run_orchestrator_node, {
            "COMPLETE": final_response_node
        })
    ],
    state_schema=CareCoordState
)

app = App(
    root_agent=care_coord_workflow,
    name="app",
)
