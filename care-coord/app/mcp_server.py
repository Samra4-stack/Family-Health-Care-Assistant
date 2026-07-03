# care-coord/app/mcp_server.py
# MCP Server — CareCoord Family Health Organizer
# Exposes 5 domain tools over stdio transport for health and care coordination.
# State is shared with the main ADK process via a JSON file on disk.

import json
import datetime
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ---------------------------------------------------------------------------
# Shared JSON data file — same path as defined in agent.py
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


# ---------------------------------------------------------------------------
# MCP Server Initialization
# ---------------------------------------------------------------------------

server = Server("care-coord-mcp")


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_prescriptions",
            description=(
                "Return all currently tracked prescriptions for the family. "
                "Each entry includes medication name, dosage, frequency, and patient name."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="list_appointments",
            description=(
                "Return all currently scheduled medical appointments for the family. "
                "Each entry includes provider, date/time, patient name, and purpose."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_upcoming_appointments",
            description=(
                "Return upcoming appointments sorted by date, up to a configurable limit. "
                "Useful for daily briefing or caregiver check-in."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of appointments to return. Defaults to 5.",
                        "default": 5
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="add_wellness_task",
            description=(
                "Add a wellness or care task to the family task list. "
                "Tasks are lightweight reminders or to-dos (e.g. 'Order refill for Sam's Amoxicillin')."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short title of the task."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional detail about the task."
                    },
                    "assignee": {
                        "type": "string",
                        "description": "Family member or caregiver this task is assigned to."
                    }
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="get_health_summary",
            description=(
                "Return a structured summary of the family's current health data: "
                "number of active prescriptions, upcoming appointments, and open wellness tasks."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
    ]


# ---------------------------------------------------------------------------
# Tool Call Handlers
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name == "list_prescriptions":
        data = _load_data()["prescriptions"]
        if not data:
            result = "No prescriptions tracked yet."
        else:
            lines = [
                f"- {p['medication']} {p['dosage']}, {p['frequency']} → {p['patient_name']}"
                for p in data
            ]
            result = "Tracked Prescriptions:\n" + "\n".join(lines)
        return [TextContent(type="text", text=result)]

    elif name == "list_appointments":
        data = _load_data()["appointments"]
        if not data:
            result = "No appointments scheduled yet."
        else:
            lines = [
                f"- {a['provider']} on {a['datetime_str']} for {a['patient_name']} ({a['purpose']})"
                for a in data
            ]
            result = "Scheduled Appointments:\n" + "\n".join(lines)
        return [TextContent(type="text", text=result)]

    elif name == "get_upcoming_appointments":
        limit = arguments.get("limit", 5)
        data = _load_data()["appointments"][:limit]
        if not data:
            result = "No upcoming appointments."
        else:
            lines = [
                f"- {a['provider']} on {a['datetime_str']} for {a['patient_name']}"
                for a in data
            ]
            result = f"Next {limit} appointments:\n" + "\n".join(lines)
        return [TextContent(type="text", text=result)]

    elif name == "add_wellness_task":
        task = {
            "title": arguments["title"],
            "description": arguments.get("description", ""),
            "assignee": arguments.get("assignee", "Caregiver"),
            "created_at": datetime.datetime.now().isoformat()
        }
        shared = _load_data()
        shared["tasks"].append(task)
        _save_data(shared)
        result = f"Task added: '{task['title']}' assigned to {task['assignee']}."
        return [TextContent(type="text", text=result)]

    elif name == "get_health_summary":
        shared = _load_data()
        result = (
            f"Family Health Summary:\n"
            f"  Active prescriptions: {len(shared['prescriptions'])}\n"
            f"  Scheduled appointments: {len(shared['appointments'])}\n"
            f"  Open wellness tasks: {len(shared['tasks'])}"
        )
        return [TextContent(type="text", text=result)]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
