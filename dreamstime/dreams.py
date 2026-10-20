"""Produce atomic, review-gated commands for the observed Dreams MCP schema.

No raw browsing history or chat excerpts enter the exported batch.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from .core import digest
from .recognition import WORK_KINDS


def build_worked_batch(report, state, installation_id, observed_at=None):
    """Replace one own-work snapshot per device, asset and week. Never add hours."""
    if not report['reviewed']:
        raise ValueError('Review assigned hours before syncing.')
    week = report['week']
    end = (datetime.fromisoformat(week) + timedelta(days=6)).date().isoformat()
    nodes = {n['id']: n for n in state.get('nodes', [])}
    totals = {}
    for project in report['projects']:
        seconds = report['totals'].get(project['id'], 0)
        target = project.get('dreams_id')
        if seconds and not target:
            raise ValueError("Connect '" + project['name'] + "' to a Dreams project before syncing.")
        if target:
            totals[target] = totals.get(target, Decimal(0)) + Decimal(str(seconds))
    # Retain zero corrections for snapshots previously written by this device.
    for target, node in nodes.items():
        ident = 'dreamstime-' + digest([installation_id, week, target])[:32]
        if any(m.get('id') == ident for m in node.get('measurements', [])):
            totals.setdefault(target, 0)
    commands = []
    for target, seconds in sorted(totals.items()):
        node = nodes.get(target)
        ident = 'dreamstime-' + digest([installation_id, week, target])[:32]
        existing = next((m for m in (node or {}).get('measurements', []) if m.get('id') == ident), None)
        hours = int((Decimal(str(seconds)) / Decimal(3600)).to_integral_value(rounding=ROUND_FLOOR))
        if hours < 1 and not existing:
            continue
        if not node or node.get('archived') or node.get('kind') not in WORK_KINDS:
            raise ValueError('A destination was removed or archived in Dreams. Check its assignments before syncing.')
        measurement = {'id': ident, 'metric': 'workedHours', 'amount': {'value': hours, 'unit': 'hours'},
                       'basis': 'Worked', 'period': {'kind': 'Week', 'start': week, 'end': end},
                       'observedAt': observed_at or datetime.now(timezone.utc).isoformat(),
                       'source': 'Dreams Time · ' + installation_id, 'scope': 'Own'}
        commands.append({'type': 'record_measurement', 'id': target, 'measurement': measurement})
    payload = {'baseRevision': state['revision'], 'commands': commands}
    # observedAt is saved with the pending batch so a retry sends identical bytes.
    return {'requestId': 'dreamstime-' + digest([installation_id, payload])[:32], **payload}


def build_batch(report, state, installation_id):
    if not report["reviewed"]:
        raise ValueError("Review this week's totals before preparing the Dreams update.")
    week = report["week"]
    projects = {p["id"]: p for p in report["projects"]}
    nodes = {n["id"]: n for n in state.get("nodes", [])}
    commands = []
    end = (datetime.fromisoformat(week) + timedelta(days=6)).date().isoformat()
    for project_id, project in projects.items():
        seconds = report["totals"].get(project_id, 0)
        target = project.get("dreams_id")
        prefix = "tracker-" + digest([installation_id, week, project_id])[:24]
        # Include previously exported zeroed weeks so corrections remove old hours.
        if not seconds and prefix not in nodes:
            continue
        if not target or target not in nodes or nodes[target].get("archived"):
            if seconds:
                raise ValueError("Link project '" + project["name"] + "' to an active Dreams project first.")
            continue
        if nodes[target].get("kind") != "project":
            raise ValueError("Dreams destination must be a Project.")
        hours = round(seconds / 3600, 6)
        fields = {"meaning": "Hours used", "amount": {"value": hours, "unit": "hours"}, "period": "Custom", "startDate": week, "endDate": end, "customPeriod": "Week of " + week + " · " + report["timezone"], "basis": "Confirmed", "status": "Complete", "description": "Reviewed computer activity. Source: Dreams Time. " + str(round(seconds, 3)) + " seconds; " + report["timezone"] + "."}
        if prefix in nodes:
            if nodes[prefix].get("kind") != "time":
                raise ValueError("Tracker record ID conflicts with a non-time node.")
            commands.append({"type": "update_node", "id": prefix, "patch": {"fields": {**nodes[prefix].get("fields", {}), **fields}, "archived": False}})
        else:
            position = nodes[target].get("position", {"x": 0, "y": 0})
            node = {"id": prefix, "kind": "time", "name": project["name"] + " · " + week, "fields": fields, "visible": {"name": True, "amount": True, "period": True}, "position": {"x": position["x"] - 260, "y": position["y"] + 180}, "checklist": [], "revision": 0}
            commands.append({"type": "create_node", "node": node})
        edge_id = prefix + "-allocation"
        if not any(e["id"] == edge_id for e in state.get("edges", [])):
            commands.append({"type": "connect", "edge": {"id": edge_id, "source": prefix, "target": target, "relation": "Allocates", "allocation": None, "visible": True, "revision": 0}})
    if not commands:
        raise ValueError("No assigned time to export for this week.")
    # Same reviewed data + same fresh map => same retry ID; changed data/revision gets a new one.
    payload = {"baseRevision": state["revision"], "commands": commands}
    return {"requestId": "dreamstime-" + digest([installation_id, report["digest"], payload])[:32], **payload}
