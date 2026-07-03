# Care Coordination Agent — Submission Write-Up

## Problem Statement
Managing complex family health schedules, tracking daily medications, and coordinating medical appointments is a fragmented and overwhelming process. Caregivers lack a centralized, intelligent assistant that can track these activities safely while ensuring they retain ultimate control over critical health decisions.

## Solution Architecture
![Architecture Diagram](assets/architecture_diagram.png)

The Care Coordination Agent is built on a multi-agent architecture using the ADK. It features a central Orchestrator that parses user intent and routes requests to specialized sub-agents or offline handlers. A dedicated Security Checkpoint intercepts all inbound messages to prevent prompt injection and scrub PII. A persistent datastore (via MCP) maintains state across sessions.

## Concepts Used
- **ADK Workflow:** Custom Python function nodes in `app/agent.py` define the exact execution path, integrating security checks before natural language processing.
- **LlmAgent:** Used for fallback natural language interactions when inputs fall outside the strict offline patterns.
- **AgentTool & MCP Server:** An MCP server (`app/mcp_server.py`) provides tools to read and write to a local JSON datastore (`app/.adk/care_data.json`), allowing state persistence across process restarts.
- **Security Checkpoint:** A dedicated node that halts execution if malicious injections or unauthorized PII are detected.
- **Agents CLI:** Scaffolded and tested locally using `agents-cli playground` and the ADK web server.

## Security Design
Given the sensitive nature of health data, the Security Checkpoint acts as the first line of defense:
- **Injection Detection:** Domain rules automatically block adversarial inputs aiming to bypass caregiver constraints.
- **PII Scrubbing:** Detects and scrubs unauthorized personal identifiers to prevent sensitive data leakage.
- **Audit Logging:** Emits JSON-formatted audit logs for every security decision, ensuring transparency and accountability.

## MCP Server Design
The MCP server acts as the persistent memory layer for the multi-agent system. It exposes dedicated tools that the agents (and offline handlers) use to interact with the family health database:
- Reads active prescriptions and wellness tasks.
- Appends newly approved appointments and medication logs to the JSON state file.

## Human-In-The-Loop (HITL) Flow
To guarantee safety in medical coordination, the agent employs a strict Human-In-The-Loop (HITL) approval process. When a user requests to schedule an appointment or log a new prescription, the Orchestrator stages the action and halts. It explicitly prompts the caregiver with the parsed details (Medication, Dosage, Patient) and requires a manual `"yes"` response before any data is written to the persistent store.

## Demo Walkthrough
1. **Stage a Prescription:** The user types `log prescription Amoxicillin 500mg daily for Sarah`. The Orchestrator's offline regex parses the details, bypasses the LLM to avoid quota issues, stages the prescription, and asks the user for confirmation.
2. **Approval:** The user replies `yes`. The orchestrator immediately identifies the pending action, commits it to the JSON datastore, and replies with a success confirmation.
3. **Summary Retrieval:** The user types `health summary`. The orchestrator fetches the latest state from the datastore and prints a formatted summary, proving the state was securely persisted.

## Impact / Value Statement
This agent significantly reduces the cognitive load on family caregivers. By automating the tracking of prescriptions and appointments—while strictly enforcing human oversight for final decisions—it prevents missed medications and scheduling conflicts, ultimately improving family health outcomes safely and reliably.
