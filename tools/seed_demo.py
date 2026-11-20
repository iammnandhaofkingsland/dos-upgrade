"""Seeds a running DOS with a believable day of activity for five clients, so no screen is empty when you present.
Usage: python tools/seed_demo.py [base_url] [password]
Works in simulation mode and in live mode (live mode calls Gemini and costs a few rupees).

It signs in as different PEOPLE (owner, operator, approver, technician, auditor) through the same API the console
uses, so the audit log, the approvals and the four-eyes rule all look the way they will in real use.
QuickCred is deliberately left half set up (loan data not connected): you finish it live on stage.
Kaveri Precision (the plant) gets one machine breakdown handled end to end, and one left open for the technician."""
import os
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else os.getenv("DQ_DEMO_PASSWORD", "DOS@2026")
http = httpx.Client(base_url=BASE + "/api", timeout=180)
USERNAMES = {"kaveri": {"owner": "plant.head", "operator": "planner", "approver": "maint.head", "quality": "quality.head",
                        "technician": "tech.mech", "technician2": "tech.elec", "auditor": "auditor"}}
_tokens: dict = {}


def token(client, role):
    """Sign in once per (client, person) and reuse the signed session token."""
    key = (client, role)
    if key not in _tokens:
        user = USERNAMES.get(client, {}).get(role, role)
        r = http.post("/auth/login", json={"client": client, "username": user, "password": PASSWORD})
        r.raise_for_status()
        _tokens[key] = r.json()["token"]
    return _tokens[key]


def call(method, path, client, role="owner", **kw):
    r = http.request(method, path, headers={"Authorization": "Bearer " + token(client, role)}, **kw)
    if r.status_code >= 400:
        raise SystemExit(f"{method} {path} as {client}/{role}: {r.status_code} {r.text[:300]}")
    return r.json()


mock = call("GET", "/meta", "demo")["mode"] == "mock"


def go_live(client, agent_id, note="Limits and approvals reviewed with the operations head. Accepted for the pilot."):
    call("POST", f"/agents/{agent_id}/activate", client, "operator", json={})
    if call("GET", f"/agents/{agent_id}/blueprint", client)["risk"]["tier"] == "High":
        call("POST", f"/agents/{agent_id}/risk-acceptance", client, "owner", json={"note": note})
    dep = call("POST", f"/agents/{agent_id}/deployments", client, "operator")
    print(f"  {client:11s} {agent_id:14s} v{dep['version']} {dep['status']}" + (f" score={dep['eval']['score']}" if dep.get("eval") else ""))
    return dep


def wait(client, rid):
    for _ in range(900):
        r = call("GET", f"/runs/{rid}", client)
        if r["status"] != "running":
            return r
        time.sleep(0.2)
    return r


def run(client, agent_id, ask=None, decision=None, minutes_ago=0):
    ask = ask or call("GET", f"/catalog/{agent_id}", client)["demo"]["ask"]
    rid = call("POST", f"/agents/{agent_id}/runs", client, "operator", json={"input": ask})["id"]
    r = wait(client, rid)
    for _ in range(4):  # an agent can ask for more than one approval in a run
        if r["status"] != "waiting_approval" or decision is None:
            break
        for ap in [a for a in r["approvals"] if a["status"] == "pending"]:
            call("POST", f"/approvals/{ap['id']}/decision", client, "approver",
                 json={"approved": decision, "note": "Checked the account history" if decision else "Need more evidence first"})
        r = wait(client, rid)
    if mock and minutes_ago:
        call("POST", f"/dev/backdate/{rid}", client, params={"minutes": minutes_ago})
    print(f"  {client:11s} run {agent_id:14s} {r['status']}")
    return rid


print("Sri Balaji Finance (lender)")
SB = "sri-balaji"
call("PUT", "/client", SB, json={"policies": {"messaging.test_clock": "11:00"}, "note": "Rehearsal: fix the clock inside contact hours"})
for a in ("loanprocess", "compliancebot", "fraudshield", "kyc-autoflow", "queryiq"):
    go_live(SB, a)
for agent, decision, ago in [("queryiq", None, 1300), ("loanprocess", True, 1180), ("compliancebot", None, 1050), ("fraudshield", None, 900), ("loanprocess", True, 760),
                             ("kyc-autoflow", True, 640), ("queryiq", None, 520), ("loanprocess", False, 410), ("compliancebot", None, 300), ("fraudshield", True, 200)]:
    run(SB, agent, decision=decision, minutes_ago=ago)
call("PUT", "/client", SB, json={"policies": {"lending.max_waiver_pct": 8}, "note": "Risk committee, November: waiver cap reduced from 10 to 8 percent"})
run(SB, "loanprocess", decision=True, minutes_ago=95)
call("PUT", "/client", SB, json={"policies": {"messaging.test_clock": "21:30"}, "note": "Rehearsal: evening clock to show the contact-hours rule"})
run(SB, "loanprocess", decision=True, minutes_ago=0)  # the reminder is queued for 08:00, not sent
call("PUT", "/client", SB, json={"policies": {"messaging.test_clock": "11:00"}, "note": "Rehearsal: clock back to daytime"})
run(SB, "queryiq", minutes_ago=30)
run(SB, "loanprocess", "Follow up on loan LN-1002. The customer says her Aadhaar is 1234 5678 9012 and asked for a small waiver.", decision=None)  # left waiting on purpose
call("POST", "/governance/selftest", SB, "auditor")

print("Marigold Clothing (online brand)")
MG = "marigold"
for a in ("returnsbot", "reviewmine", "contentgen", "inventoryiq", "pricewatch"):
    go_live(MG, a)
for agent, decision, ago in [("returnsbot", None, 1200), ("contentgen", True, 1000), ("inventoryiq", True, 800), ("reviewmine", None, 600),
                             ("pricewatch", False, 420), ("returnsbot", None, 260), ("contentgen", True, 120), ("inventoryiq", None, 0)]:
    run(MG, agent, decision=decision, minutes_ago=ago)
call("POST", "/governance/selftest", MG, "auditor")

print("CarePoint Clinic")
CP = "carepoint"
call("PUT", "/client", CP, json={"policies": {"messaging.test_clock": "10:30"}, "note": "Rehearsal clock"})
for a in ("apptiq", "claimssmart"):
    go_live(CP, a)
for agent, decision, ago in [("apptiq", True, 900), ("claimssmart", None, 500), ("apptiq", True, 150), ("apptiq", None, 0)]:
    run(CP, agent, decision=decision, minutes_ago=ago)

print("QuickCred Micro Loans (left half set up on purpose)")
QC = "quickcred"
call("PUT", "/client", QC, json={"policies": {"messaging.test_clock": "11:00"}, "note": "Rehearsal clock"})
call("POST", "/agents/loanprocess/activate", QC, "operator", json={})
call("POST", "/agents/loanprocess/risk-acceptance", QC, "owner", json={"note": "Every message and every waiver is approved by a second person. Accepted."})
dep = call("POST", "/agents/loanprocess/deployments", QC, "operator")
print(f"  quickcred   loanprocess    v{dep['version']} {dep['status']}  <- blocked: loan data is not connected. Upload server/sample_data/quickcred_loans.csv on stage.")
go_live(QC, "compliancebot")
run(QC, "compliancebot")
call("POST", "/governance/selftest", QC, "auditor")

print("Kaveri Precision Components (the plant)")
KV = "kaveri"
for a in ("machinewatch", "rootcauseiq", "fixdispatch", "sparesense", "plansync", "lottrace", "oeepulse", "predictmaint", "qualitylens", "shiftbrief", "energywatch", "materialflow", "matchguard"):
    go_live(KV, a)
for agent, decision, ago in [("oeepulse", None, 600), ("shiftbrief", None, 480), ("qualitylens", True, 300), ("matchguard", True, 200), ("predictmaint", True, 90)]:
    run(KV, agent, decision=decision, minutes_ago=ago)


def wait_incident(machine, want, timeout=240):
    """Wait for the live plant loop (DQ_PLANT_LOOP=1 on the server) to detect, diagnose and dispatch."""
    for _ in range(timeout):
        st = call("GET", "/plant/state", KV)
        inc = next((i for i in st["incidents"] if i["machine"] == machine and i["status"] != "resolved"), None)
        if inc and want(inc):
            return inc
        time.sleep(1)
    raise SystemExit(f"{machine}: the plant did not respond in {timeout} s. Is the server running with DQ_PLANT_LOOP=1?")


def approve_all(role, tools):
    for ap in call("GET", "/approvals", KV, role):
        if ap["status"] == "pending" and ap["tool"] in tools:
            call("POST", f"/approvals/{ap['id']}/decision", KV, role, json={"approved": True, "note": "Checked stock and the lot list. Approved."})
            print(f"  kaveri      approved {ap['tool']} as {role}")


# breakdown 1: handled end to end (approvals, technician repair, learning)
call("POST", "/plant/faults", KV, "operator", json={"machine": "LTH-101", "fault": "spindle_bearing_wear"})
inc = wait_incident("LTH-101", lambda i: i.get("work_order") and len(i.get("runs", [])) >= 6)
print(f"  kaveri      LTH-101 incident {inc['id']}: {inc['root_cause']} ({round(inc['confidence'] * 100)}%), work order {inc['work_order']}")
time.sleep(2)
approve_all("approver", {"order_spare_part"}); approve_all("quality", {"hold_lot"})  # maintenance head buys spares, quality head holds lots
wo = inc["work_order"]
for action in ("ack", "start"):
    call("POST", f"/workorders/{wo}/{action}", KV, "technician", json={})
call("POST", f"/workorders/{wo}/resolve", KV, "technician", json={"confirmed_cause": "spindle_bearing_wear", "minutes": 95,
     "notes": "Front spindle bearing pitted. Replaced the matched pair, set preload, ran in at 50 percent speed for 20 minutes."})
print(f"  kaveri      {wo} resolved by the technician; the repair joins the history")
# breakdown 2: left open so the technician screen and the escalation have something to show
call("POST", "/plant/faults", KV, "operator", json={"machine": "PRS-501", "fault": "hydraulic_leak"})
inc = wait_incident("PRS-501", lambda i: i.get("work_order") is not None)
print(f"  kaveri      PRS-501 incident {inc['id']} open, work order {inc['work_order']} waiting for the technician")
call("POST", "/governance/selftest", KV, "auditor")
print("done. Kaveri has an open press breakdown; Sri Balaji has one approval waiting; QuickCred LoanProcess is waiting for its data.")
