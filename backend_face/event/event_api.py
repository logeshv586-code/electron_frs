from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from auth.storage import get_settings
from db.core import execute, fetch_all, fetch_one
from db.repository import (
    LOCAL_TZ,
    blob_to_vector,
    get_attendance_aggregate,
    get_attendance_rows,
    list_persons,
    list_recognition_events,
    load_face_templates,
    parse_dt,
)
from fr1 import encode_face_image

logger = logging.getLogger(__name__)
router = APIRouter()

BACKEND_DIR = Path(__file__).resolve().parents[1]
CAPTURED_ROOT = BACKEND_DIR / "captured_faces"


def _user(request: Optional[Request]) -> Dict[str, Any]:
    return (request.scope.get("user", {}) if request else {}) or {}


def _tenant(request: Request, requested: Optional[str] = None, allow_all_superadmin: bool = False) -> Optional[str]:
    user = _user(request)
    role = user.get("role")
    own = str(user.get("company_id") or "default")
    if role == "SuperAdmin":
        if requested:
            return str(requested)
        return None if allow_all_superadmin else own
    if requested and str(requested) != own:
        raise HTTPException(status_code=403, detail="Cannot access another tenant")
    return own


def _validate_date(value: Optional[str], default_today: bool = False) -> Optional[str]:
    if not value:
        return datetime.now(LOCAL_TZ).date().isoformat() if default_today else None
    try:
        return date.fromisoformat(value).isoformat()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")


def _image_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if str(path).startswith("s3://"):
        try:
            from storage.evidence_store import get_evidence_store
            return get_evidence_store().api_url(str(path))
        except Exception:
            return None
    try:
        absolute = Path(path)
        if not absolute.is_absolute():
            absolute = (BACKEND_DIR / path).resolve()
        relative = absolute.resolve().relative_to(CAPTURED_ROOT.resolve())
        parts = relative.parts
        if len(parts) >= 5 and parts[0] == "known":
            _, company, camera, person, filename = parts[:5]
            return f"/api/captured/image/known/{company}/{camera}/{person}/{filename}"
        if len(parts) >= 5 and parts[0] == "unknown":
            _, company, camera, cluster, filename = parts[:5]
            return f"/api/captured/image/unknown/{company}/{camera}/{cluster}/{filename}"
    except Exception:
        pass
    return None


def _event_view(event: Dict[str, Any]) -> Dict[str, Any]:
    timestamp = event.get("captured_at")
    return {
        "id": event.get("id"),
        "name": event.get("display_name") or (event.get("unknown_cluster_id") if event.get("event_type") == "unknown" else event.get("person_key")) or "Unknown",
        "person_key": event.get("person_key"),
        "unknown_cluster_id": event.get("unknown_cluster_id"),
        "image_path": _image_url(event.get("image_path")),
        "timestamp": timestamp,
        "type": event.get("event_type"),
        "camera": event.get("camera_name") or "Unknown Camera",
        "location": event.get("location") or event.get("camera_name") or "Unknown",
        "camera_role": event.get("camera_role") or "BIDIRECTIONAL",
        "direction": event.get("direction") or "AUTO",
        "company_id": event.get("company_id"),
        "confidence": event.get("confidence"),
        "distance": event.get("distance"),
        "quality": event.get("quality"),
        "attendance_eligible": bool(event.get("attendance_eligible")),
    }


def _filter_assigned_cameras(request: Request, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    user = _user(request)
    role = user.get("role")
    if role in {"SuperAdmin", "Admin"}:
        return events
    assigned = user.get("assigned_cameras") or []
    if not assigned:
        return []
    allowed = {str(value).lower() for value in assigned}
    return [
        event for event in events
        if str(event.get("camera_id") or "").lower() in allowed
        or str(event.get("camera_name") or "").lower() in allowed
    ]


async def filter_faces_logic(
    request: Optional[Request] = None,
    name: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    camera: Optional[str] = "all_cameras",
    face_type: Optional[str] = None,
    company_id: Optional[str] = None,
):
    if request is None:
        tenant = company_id or "default"
    else:
        tenant = _tenant(request, company_id, allow_all_superadmin=True)
    from_date = _validate_date(from_date)
    to_date = _validate_date(to_date)
    events = list_recognition_events(
        tenant,
        face_type=face_type,
        name=name,
        from_date=from_date,
        to_date=to_date,
        camera=camera,
        limit=5000,
    )
    if request is not None:
        events = _filter_assigned_cameras(request, events)
    return [_event_view(event) for event in events]


@router.get("/filter")
async def filter_faces(
    request: Request,
    name: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    camera: Optional[str] = "all_cameras",
    face_type: Optional[str] = None,
    company_id: Optional[str] = None,
):
    return await filter_faces_logic(request, name, from_date, to_date, camera, face_type, company_id)


@router.get("/cameras")
async def event_cameras(request: Request):
    tenant = _tenant(request, allow_all_superadmin=True)
    user = _user(request)
    if tenant is None:
        rows = fetch_all("SELECT DISTINCT id,name FROM cameras WHERE name IS NOT NULL ORDER BY name")
    else:
        rows = fetch_all("SELECT DISTINCT id,name FROM cameras WHERE company_id=? AND name IS NOT NULL ORDER BY name", (tenant,))
    if user.get("role") == "Supervisor":
        assigned = {str(value).lower() for value in user.get("assigned_cameras") or []}
        rows = [row for row in rows if str(row.get("id") or "").lower() in assigned or str(row.get("name") or "").lower() in assigned]
    return {"cameras": [row["name"] for row in rows]}


@router.get("/directories")
async def get_directories(request: Request):
    # Do not expose physical server paths. Kept as a compatibility endpoint.
    return {"known_faces_dir": "managed-storage", "unknown_faces_dir": "managed-storage"}


@router.post("/match-face")
async def match_face(request: Request, image: UploadFile = File(...), company_id: Optional[str] = None):
    tenant = _tenant(request, company_id)
    data = await image.read()
    probe = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if probe is None:
        raise HTTPException(status_code=400, detail="Invalid image")
    embedding = encode_face_image(probe, num_jitters=2)
    if embedding is None:
        raise HTTPException(status_code=400, detail="Exactly one clear face is required")
    matrix, names, meta = load_face_templates(tenant)
    if matrix.shape[0] == 0:
        return []
    distances = np.linalg.norm(matrix - embedding.reshape(1, -1), axis=1)
    ranked = np.argsort(distances)
    seen = set()
    output = []
    settings = get_settings(tenant).get("recognition", {})
    threshold = float(settings.get("known_distance_threshold", 0.46))
    for index in ranked:
        name = names[int(index)]
        if name in seen:
            continue
        seen.add(name)
        distance = float(distances[int(index)])
        if distance > threshold:
            continue
        person = fetch_one("SELECT * FROM persons WHERE company_id=? AND person_key=?", (tenant, name)) or {}
        output.append({
            "name": person.get("name") or name,
            "person_key": name,
            "confidence": max(0.0, 1.0 - distance),
            "distance": distance,
            "image_path": person.get("photo_path"),
            "timestamp": person.get("registration_date"),
        })
        if len(output) >= 10:
            break
    return output


@router.post("/match-face-unknown")
async def match_face_unknown(request: Request, image: UploadFile = File(...)):
    tenant = _tenant(request)
    data = await image.read()
    probe = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if probe is None:
        raise HTTPException(status_code=400, detail="Invalid image")
    embedding = encode_face_image(probe, num_jitters=1)
    if embedding is None:
        raise HTTPException(status_code=400, detail="A clear face is required")
    embedding = embedding.astype(np.float32)
    norm = float(np.linalg.norm(embedding))
    if norm:
        embedding /= norm
    rows = fetch_all("SELECT * FROM unknown_clusters WHERE company_id=? ORDER BY last_seen DESC LIMIT 2000", (tenant,))
    matches = []
    for row in rows:
        centroid = blob_to_vector(row.get("centroid"))
        if centroid.size != embedding.size:
            continue
        c_norm = float(np.linalg.norm(centroid))
        if c_norm <= 0:
            continue
        similarity = float(np.dot(embedding, centroid / c_norm))
        if similarity >= 0.82:
            matches.append({
                "name": row.get("cluster_key"),
                "confidence": similarity,
                "timestamp": row.get("last_seen"),
                "image_path": _image_url(row.get("best_image_path")),
            })
    matches.sort(key=lambda item: item["confidence"], reverse=True)
    return matches[:20]


def _attendance_company(request: Request) -> str:
    return str(_tenant(request) or "default")


def _apply_attendance_policy(company_id: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    settings = get_settings(company_id).get("attendance", {})
    punch_in = str(settings.get("punch_in", "09:30"))
    grace = int(settings.get("grace_minutes", 15) or 0)
    try:
        hour, minute = [int(part) for part in punch_in.split(":")[:2]]
    except Exception:
        hour, minute = 9, 30

    for row in rows:
        first = parse_dt(row.get("punch_in_iso"))
        row["is_late"] = False
        if first:
            local_first = first.astimezone(LOCAL_TZ)
            threshold = local_first.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(minutes=grace)
            row["is_late"] = local_first > threshold
        # Keep Present as the attendance state; Late is a separate flag so dashboard
        # counts do not accidentally treat late employees as absent.
        if row.get("punch_in_iso"):
            row["status"] = "Present"
        else:
            row["status"] = "Absent"
    return rows


async def get_attendance_logic(request: Request, target_date: Optional[str] = None):
    target_date = _validate_date(target_date, default_today=True)
    company_id = _attendance_company(request)
    rows = _apply_attendance_policy(company_id, get_attendance_rows(company_id, target_date))
    return {"date": target_date, "attendance": rows}


@router.get("/attendance")
async def get_attendance(request: Request, target_date: Optional[str] = None):
    return await get_attendance_logic(request, target_date)


@router.get("/attendance/aggregate")
async def attendance_aggregate(request: Request, start_date: str, end_date: str):
    start_date = _validate_date(start_date)
    end_date = _validate_date(end_date)
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date must be before end_date")
    company_id = _attendance_company(request)
    # Calculate late days from daily session rows so tenant policy is applied consistently.
    aggregate = {row["person_id"]: row for row in get_attendance_aggregate(company_id, start_date, end_date)}
    current = date.fromisoformat(start_date)
    finish = date.fromisoformat(end_date)
    while current <= finish:
        daily = _apply_attendance_policy(company_id, get_attendance_rows(company_id, current.isoformat()))
        for row in daily:
            if row.get("is_late") and row.get("person_id") in aggregate:
                aggregate[row["person_id"]]["total_late"] = aggregate[row["person_id"]].get("total_late", 0) + 1
        current += timedelta(days=1)
    return {"start_date": start_date, "end_date": end_date, "aggregate": list(aggregate.values())}


@router.get("/attendance/weekly")
async def attendance_weekly(request: Request):
    company_id = _attendance_company(request)
    today = datetime.now(LOCAL_TZ).date()
    weekly = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        rows = _apply_attendance_policy(company_id, get_attendance_rows(company_id, day.isoformat()))
        weekly.append({
            "date": day.isoformat(),
            "day": day.strftime("%a"),
            "present": sum(1 for row in rows if row["status"] == "Present"),
            "absent": sum(1 for row in rows if row["status"] == "Absent"),
            "late": sum(1 for row in rows if row.get("is_late")),
            "total": len(rows),
        })
    return {"weekly": weekly}


@router.get("/attendance/department-stats")
async def get_department_stats(request: Request, target_date: Optional[str] = None):
    data = await get_attendance_logic(request, target_date)
    departments: Dict[str, Dict[str, int]] = {}
    for row in data["attendance"]:
        department = row.get("department") or "Unassigned"
        item = departments.setdefault(department, {"present": 0, "absent": 0, "late": 0, "total": 0})
        item["total"] += 1
        if row["status"] == "Present":
            item["present"] += 1
        else:
            item["absent"] += 1
        if row.get("is_late"):
            item["late"] += 1
    return {"date": data["date"], "departments": departments}


async def get_dashboard_stats_logic(request: Request, target_date: Optional[str] = None):
    data = await get_attendance_logic(request, target_date)
    rows = data["attendance"]
    events = list_recognition_events(_attendance_company(request), from_date=data["date"], to_date=data["date"], limit=10000)
    return {
        "total_employees": len(rows),
        "present_today": sum(1 for row in rows if row["status"] == "Present"),
        "absent": sum(1 for row in rows if row["status"] == "Absent"),
        "late": sum(1 for row in rows if row.get("is_late")),
        "known_events": sum(1 for event in events if event.get("event_type") == "known"),
        "unknown_events": sum(1 for event in events if event.get("event_type") == "unknown"),
    }


@router.get("/dashboard-stats")
async def dashboard_stats(request: Request, target_date: Optional[str] = None):
    return await get_dashboard_stats_logic(request, target_date)


@router.get("/dashboard")
async def dashboard(request: Request, target_date: Optional[str] = None):
    attendance = await get_attendance_logic(request, target_date)
    return {
        "date": attendance["date"],
        "stats": await get_dashboard_stats_logic(request, attendance["date"]),
        "attendance": attendance["attendance"],
    }


def _csv_response(filename: str, headers: List[str], rows: List[List[Any]]) -> StreamingResponse:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    stream.seek(0)
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/employees/export")
async def export_employees(request: Request):
    persons = list_persons(_attendance_company(request))
    return _csv_response(
        "employees_export.csv",
        ["Emp ID", "Name", "Email", "Phone", "Department", "Designation", "Role", "Status", "Joining Date"],
        [[
            person.get("emp_id") or "", person.get("name") or "", person.get("email") or "", person.get("phone") or "",
            person.get("department") or "", person.get("designation") or "", person.get("role") or "", person.get("status") or "",
            person.get("joining_date") or "",
        ] for person in persons],
    )


@router.get("/attendance/export")
async def export_attendance_csv(request: Request, target_date: Optional[str] = None):
    data = await get_attendance_logic(request, target_date)
    return _csv_response(
        f"attendance_report_{data['date']}.csv",
        ["S.No", "Emp ID", "Name", "Department", "Designation", "Status", "Punch In", "Punch Out", "Working Hours", "Late"],
        [[
            row.get("s_no"), row.get("emp_id"), row.get("name"), row.get("department"), row.get("designation"), row.get("status"),
            row.get("punch_in") or "", row.get("punch_out") or "", row.get("working_hours") or "-", "Yes" if row.get("is_late") else "No",
        ] for row in data["attendance"]],
    )


def _report_pdf(title: str, headers: List[str], rows: List[List[Any]], subtitle: str = "") -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF dependency unavailable: {exc}")

    buffer = io.BytesIO()
    page = landscape(A4) if len(headers) > 7 else A4
    doc = SimpleDocTemplate(buffer, pagesize=page, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm, bottomMargin=12 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("FRSTitle", parent=styles["Title"], fontSize=15, textColor=colors.HexColor("#1e3a5f"), spaceAfter=4)
    small = ParagraphStyle("FRSSmall", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#64748b"))
    story = [Paragraph("Face Recognition Attendance", title_style), Paragraph(title, styles["Heading2"])]
    if subtitle:
        story.append(Paragraph(subtitle, small))
    story.append(Spacer(1, 5 * mm))
    data = [headers] + [["" if value is None else str(value) for value in row] for row in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef4ff")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7e0ea")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    doc.build(story)
    return buffer.getvalue()


@router.get("/export/attendance-pdf")
async def attendance_pdf(request: Request, target_date: Optional[str] = None):
    data = await get_attendance_logic(request, target_date)
    headers = ["#", "Emp ID", "Name", "Department", "Status", "In", "Out", "Hours", "Late"]
    rows = [[
        row.get("s_no"), row.get("emp_id"), row.get("name"), row.get("department"), row.get("status"), row.get("punch_in") or "-",
        row.get("punch_out") or "-", row.get("working_hours") or "-", "Yes" if row.get("is_late") else "No",
    ] for row in data["attendance"]]
    pdf = _report_pdf(f"Daily Attendance — {data['date']}", headers, rows)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=attendance_report_{data['date']}.pdf"})


@router.get("/export/attendance-aggregate-pdf")
async def attendance_aggregate_pdf(request: Request, start_date: str, end_date: str):
    data = await attendance_aggregate(request, start_date, end_date)
    headers = ["#", "Emp ID", "Name", "Department", "Present", "Absent", "Late", "Total Hours", "Avg/Day"]
    rows = [[
        row.get("s_no"), row.get("emp_id"), row.get("name"), row.get("department"), row.get("total_present"), row.get("total_absent"),
        row.get("total_late"), row.get("total_working_hours"), row.get("avg_working_hours"),
    ] for row in data["aggregate"]]
    pdf = _report_pdf(f"Attendance Summary — {start_date} to {end_date}", headers, rows)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=attendance_aggregate_{start_date}_to_{end_date}.pdf"})


@router.get("/export/dashboard-pdf")
async def dashboard_pdf(request: Request, target_date: Optional[str] = None):
    data = await dashboard(request, target_date)
    stats = data["stats"]
    headers = ["Name", "Department", "In", "Out", "Status"]
    rows = [[row.get("name"), row.get("department"), row.get("punch_in") or "-", row.get("punch_out") or "-", row.get("status")] for row in data["attendance"]]
    subtitle = f"Present {stats['present_today']} • Absent {stats['absent']} • Late {stats['late']} • Unknown events {stats['unknown_events']}"
    pdf = _report_pdf(f"Dashboard — {data['date']}", headers, rows, subtitle)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=dashboard_{data['date']}.pdf"})


@router.delete("/delete")
async def delete_event_evidence(request: Request, image_path: str = Query(...)):
    if str(_user(request).get("role", "")).lower() != "superadmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can delete event evidence")

    # Accept either the public image URL or stored path. Deleting evidence never deletes
    # the recognition event or attendance session.
    event = None
    if image_path.startswith("/api/captured/image/"):
        filename = Path(image_path.split("?", 1)[0]).name
        event = fetch_one("SELECT * FROM recognition_events WHERE image_path LIKE ? ORDER BY captured_at DESC LIMIT 1", (f"%{filename}",))
    else:
        event = fetch_one("SELECT * FROM recognition_events WHERE image_path=? ORDER BY captured_at DESC LIMIT 1", (image_path,))
    if not event:
        raise HTTPException(status_code=404, detail="Evidence not found")
    stored = event.get("image_path")
    if stored:
        try:
            path = Path(stored).resolve()
            path.relative_to(CAPTURED_ROOT.resolve())
            if path.exists():
                path.unlink()
        except ValueError:
            raise HTTPException(status_code=403, detail="Invalid evidence path")
    execute("UPDATE recognition_events SET image_path=NULL WHERE id=?", (event["id"],))
    return {"status": "success", "message": "Evidence deleted; recognition and attendance history preserved"}
