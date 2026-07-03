import json
import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="CareCoord HTTP API", version="0.1.0")

# Shared JSON data file – same location as used by the MCP server and agent
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

@app.get("/health_summary")
async def health_summary():
    data = _load_data()
    return {
        "active_prescriptions": len(data.get("prescriptions", [])),
        "scheduled_appointments": len(data.get("appointments", [])),
        "open_wellness_tasks": len(data.get("tasks", [])),
    }

@app.get("/prescriptions")
async def list_prescriptions():
    return _load_data().get("prescriptions", [])

@app.get("/appointments")
async def list_appointments():
    return _load_data().get("appointments", [])

@app.get("/upcoming_appointments")
async def upcoming_appointments(limit: int = 5):
    return _load_data().get("appointments", [])[:limit]

class WellnessTask(BaseModel):
    title: str
    description: Optional[str] = ""
    assignee: Optional[str] = "Caregiver"

@app.post("/add_wellness_task")
async def add_wellness_task(task: WellnessTask):
    shared = _load_data()
    new_task = {
        "title": task.title,
        "description": task.description,
        "assignee": task.assignee,
        "created_at": datetime.datetime.now().isoformat()
    }
    shared.setdefault("tasks", []).append(new_task)
    _save_data(shared)
    return {"result": f"Task added: '{task.title}' assigned to {task.assignee}."}

@app.get("/health_summary_text")
async def health_summary_text():
    data = _load_data()
    summary = (
        f"Family Health Summary:\n"
        f"  Active prescriptions: {len(data.get('prescriptions', []))}\n"
        f"  Scheduled appointments: {len(data.get('appointments', []))}\n"
        f"  Open wellness tasks: {len(data.get('tasks', []))}"
    )
    return {"summary": summary}
