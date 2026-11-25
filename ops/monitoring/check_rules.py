#!/usr/bin/env python3
"""Offline sanity checks for the monitoring files (stdlib + pyyaml).

Not a PromQL evaluator: use promtool for that (see docs/monitoring.md).
Run from anywhere: python3 ops/monitoring/check_rules.py
"""
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MON = ROOT / "ops" / "monitoring"
errors = []


def err(msg):
    errors.append(msg)


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of keeping the last one."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load(path):
    try:
        return yaml.load(path.read_text(), Loader=StrictLoader)  # noqa: S506 - SafeLoader subclass
    except Exception as e:  # noqa: BLE001
        err(f"{path}: invalid YAML: {e}")
        return None


def iter_rules(doc, path):
    if not isinstance(doc, dict) or not isinstance(doc.get("groups"), list):
        err(f"{path}: missing 'groups' list")
        return
    for g in doc["groups"]:
        if "name" not in g or not isinstance(g.get("rules"), list):
            err(f"{path}: group without name/rules")
            continue
        for r in g["rules"]:
            yield r


known_text = (ROOT / "docs" / "monitoring-contract.md").read_text() + (
    ROOT / "backend" / "roletailor" / "api" / "metrics.py"
).read_text()
known = set(re.findall(r"roletailor_[a-z0-9_]+", known_text))
# histogram series derived from a known base name
derived = {m + s for m in known for s in ("_bucket", "_sum", "_count")}
known |= derived
recorded = set()

rec_path, alert_path = MON / "prometheus/rules/recording.yml", MON / "prometheus/rules/alerts.yml"
rec_doc, alert_doc = load(rec_path), load(alert_path)

runbook = (ROOT / "docs/runbooks/ai-alerts.md").read_text()
anchors = {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
           for h in re.findall(r"^#+\s+(.+)$", runbook, re.M)}

exprs = []
for r in iter_rules(rec_doc, rec_path) or []:
    if "record" not in r or "expr" not in r:
        err(f"recording rule missing record/expr: {r}")
        continue
    recorded.add(r["record"])
    exprs.append((r["record"], r["expr"]))

names = []
for r in iter_rules(alert_doc, alert_path) or []:
    n = r.get("alert")
    if not n or "expr" not in r:
        err(f"alert without name/expr: {r}")
        continue
    names.append(n)
    exprs.append((n, r["expr"]))
    sev = (r.get("labels") or {}).get("severity")
    if sev not in ("warning", "critical"):
        err(f"{n}: severity must be warning|critical, got {sev!r}")
    ann = r.get("annotations") or {}
    for k in ("summary", "description", "runbook_url"):
        if not ann.get(k):
            err(f"{n}: missing annotation {k}")
    if "$value" not in str(ann.get("description", "")) and n not in ("WorkerMetricsDown", "ApiDown"):
        err(f"{n}: description should show the current value")
    url = ann.get("runbook_url", "")
    m = re.fullmatch(r"docs/runbooks/ai-alerts\.md#([a-z0-9-]+)", url)
    if not m:
        err(f"{n}: runbook_url has unexpected form: {url}")
    elif m.group(1) != n.lower():
        err(f"{n}: runbook anchor should be {n.lower()}")
    elif m.group(1) not in anchors:
        err(f"{n}: runbook anchor #{m.group(1)} not found in docs/runbooks/ai-alerts.md")
    if not r.get("for") and n not in ():
        err(f"{n}: missing 'for'")
if len(names) != len(set(names)):
    err("duplicate alert names")

# dashboards
dash_exprs = []
for f in sorted((MON / "grafana/dashboards").glob("*.json")):
    try:
        d = json.loads(f.read_text())
    except Exception as e:  # noqa: BLE001
        err(f"{f}: invalid JSON: {e}")
        continue
    if d.get("schemaVersion") != 39 or not d.get("uid"):
        err(f"{f}: needs uid and schemaVersion 39")
    for p in d.get("panels", []):
        for t in p.get("targets", []):
            if "expr" in t:
                dash_exprs.append((f"{f.name}:{p.get('title')}", t["expr"]))
            if "rawSql" in t and "roletailor_ops." not in t["rawSql"]:
                err(f"{f.name}:{p.get('title')}: SQL does not use roletailor_ops")

for where, e in exprs + dash_exprs:
    for token in re.findall(r"roletailor:[a-z0-9_:]+|roletailor_[a-z0-9_]+", e):
        if token.startswith("roletailor:"):
            if token not in recorded:
                err(f"{where}: recording rule {token} is not defined")
        elif token not in known:
            err(f"{where}: metric {token} not in contract or metrics.py")

for rel in ("prometheus/prometheus.yml", "alertmanager/alertmanager.yml",
            "grafana/provisioning/datasources/datasources.yml",
            "grafana/provisioning/dashboards/dashboards.yml"):
    load(MON / rel)
load(ROOT / "docker-compose.monitoring.yml")
load(MON / "prometheus/tests/alerts_test.yml")

# every contract recording rule exists
contract = (ROOT / "docs/monitoring-contract.md").read_text()
for name in re.findall(r"`(roletailor:[a-z0-9_:]+)`", contract):
    if name not in recorded:
        err(f"contract recording rule {name} not defined")

if errors:
    print("FAILED")
    print("\n".join(" - " + e for e in errors))
    sys.exit(1)
print(f"OK: {len(recorded)} recording rules, {len(names)} alerts, "
      f"{len(dash_exprs)} dashboard queries checked")
