"""
vehicle_issues.py
-----------------
Detects and counts vehicle issues from condition fields.

Usage
-----
    from utils.vehicle_issues import detect_vehicle_issues

    result = detect_vehicle_issues(vehicle_dict)
    # result → {"issueCount": 2, "issues": [{"name": "...", "severity": "Medium"}, ...]}
"""


def detect_vehicle_issues(vehicle: dict) -> dict:
    """
    Analyse vehicle condition fields and return a structured issue report.

    Parameters
    ----------
    vehicle : dict
        Vehicle data dictionary (as produced by ``Vehicle.to_dict()``).
        Relevant keys:
            - accident_history   : "No" | "Minor" | "Major" | "NA"
            - loan_status        : "No Loan" | "Closed" | "Active" | "NA"
            - rc_service_records : "Yes" | "No" | "NA"
            - keys_available     : "Two" | "One" | "NA"
            - body_panel_status  : "Original" | "Repainted" | "Replaced" | "NA"
            - major_issues       : comma-separated string e.g. "Engine,AC" | "None" | "NA"

    Returns
    -------
    dict
        {
            "issueCount": <int>,
            "issues": [
                {"name": "<str>", "severity": "Low | Medium | High"},
                ...
            ]
        }
    """
    issues = []

    # ── 1. Accident History ───────────────────────────────────────────────────
    accident = (vehicle.get("accident_history") or "NA").strip()
    if accident == "Minor":
        issues.append({"name": "Minor Accident History", "severity": "Medium"})
    elif accident == "Major":
        issues.append({"name": "Major Accident History", "severity": "High"})
    # "No" and "NA" → no issue

    # ── 2. Loan / Hypothecation ───────────────────────────────────────────────
    loan = (vehicle.get("loan_status") or "NA").strip()
    if loan == "Active":
        issues.append({"name": "Active Loan / Hypothecation", "severity": "Medium"})
    # "No Loan", "Closed", "NA" → no issue

    # ── 3. RC & Service Records ───────────────────────────────────────────────
    rc = (vehicle.get("rc_service_records") or "NA").strip()
    if rc == "No":
        issues.append({"name": "RC & Service Records Unavailable", "severity": "Low"})
    # "Yes" and "NA" → no issue

    # ── 4. Keys Available ─────────────────────────────────────────────────────
    keys = (vehicle.get("keys_available") or "NA").strip()
    if keys == "One":
        issues.append({"name": "Only One Key Available", "severity": "Low"})
    # "Two" and "NA" → no issue

    # ── 5. Body Panel Status ─────────────────────────────────────────────────
    body = (vehicle.get("body_panel_status") or "NA").strip()
    if body == "Repainted":
        issues.append({"name": "Body Panel Repainted", "severity": "Medium"})
    elif body == "Replaced":
        issues.append({"name": "Body Panel Replaced", "severity": "High"})
    # "Original" and "NA" → no issue

    # ── 6. Major Issues (multi-select, comma-separated) ───────────────────────
    _MAJOR_ISSUE_MAP = {
        "Engine":     ("Engine Issue",     "High"),
        "Gearbox":    ("Gearbox Issue",    "High"),
        "AC":         ("AC Issue",         "Medium"),
        "Suspension": ("Suspension Issue", "High"),
    }
    raw_major = (vehicle.get("major_issues") or "None").strip()
    if raw_major.lower() not in ("none", "na", ""):
        for part in raw_major.split(","):
            part = part.strip()
            if part in _MAJOR_ISSUE_MAP:
                name, severity = _MAJOR_ISSUE_MAP[part]
                issues.append({"name": name, "severity": severity})

    return {
        "issueCount": len(issues),
        "issues": issues,
    }


def severity_order(issue: dict) -> int:
    """Return sort key so High > Medium > Low."""
    return {"High": 0, "Medium": 1, "Low": 2}.get(issue.get("severity", "Low"), 3)
