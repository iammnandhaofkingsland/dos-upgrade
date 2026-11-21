"""End-to-end tests for all five layers. They need no network and no API key (mock model, in-memory store).
Run:  cd server && DQ_MODEL_MODE=mock pytest -q

The tests are grouped by layer so a failing test tells you which layer broke:
  core (agents work at all) -> layer 2 config -> layer 3 data -> layer 4 agents -> layer 5 governance -> layer 1 console"""
import os
import pathlib

os.environ["DQ_MODEL_MODE"] = "mock"
os.environ["DQ_STORE"] = "memory"
os.environ["DQ_AUTH_MODE"] = "headers"   # tests state client and role in headers; sign-in has its own tests below
os.environ["DQ_PLANT_LOOP"] = "0"        # tests advance the plant step by step

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from dq.clients import as_client  # noqa: E402
from dq.plugins import mask_pii  # noqa: E402
from dq.spec import load_catalog  # noqa: E402
from dq.store import get_store, reset_store  # noqa: E402
from dq.tools import REGISTRY  # noqa: E402
from dq.tools.commerce import update_price  # noqa: E402
from dq.tools.services import run_sql  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent


def H(client_id="demo", role="owner"):
    """Headers that say which client and which role the caller is."""
    return {"X-DQ-Client": client_id, "X-DQ-Role": role}


@pytest.fixture()
def client():
    from dq import plant  # noqa: PLC0415

    reset_store()
    plant.reset_plants()
    import main  # noqa: PLC0415

    with TestClient(main.create_app()) as c:
        yield c


def wait_run(client, run_id, until=("completed", "failed", "waiting_approval", "stopped"), headers=None):
    import time  # noqa: PLC0415

    for _ in range(100):
        run = client.get(f"/api/runs/{run_id}", headers=headers).json()
        if run["status"] in until:
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def go_live(client, agent_id, headers=None, accept_risk=True, settings=None):
    """Activate, accept risk if the agent is High-risk, deploy. Returns the deployment."""
    assert client.post(f"/api/agents/{agent_id}/activate", json=settings or {}, headers=headers).status_code == 200
    if accept_risk and client.get(f"/api/agents/{agent_id}/blueprint", headers=headers).json()["risk"]["tier"] == "High":
        r = client.post(f"/api/agents/{agent_id}/risk-acceptance", json={"note": "Reviewed limits and approvals; accepted for the pilot."}, headers=headers)
        assert r.status_code == 200, r.text
    return client.post(f"/api/agents/{agent_id}/deployments", headers=headers).json()


# ------------------------------------------------------------------ core
def test_catalog_is_valid():
    cat = load_catalog()
    assert len(cat) == 55
    for spec in cat.values():
        assert all(t in REGISTRY for t in spec.tools), spec.id
        assert spec.evals, f"{spec.id} has no eval case"


def test_guardrails_in_tools():
    reset_store()
    assert run_sql("DROP TABLE orders")["status"] == "error"
    assert run_sql("SELECT phone FROM customers")["status"] == "error"
    assert run_sql("SELECT * FROM customers")["status"] == "error"
    assert run_sql("SELECT COUNT(*) FROM orders")["status"] == "success"
    assert update_price("SKU-204", 500)["status"] == "error"  # below margin floor


def test_pii_masking():
    text, hits = mask_pii("My Aadhaar is 1234 5678 9012 and PAN ABCPB1234K")
    assert hits == 2 and "1234 5678" not in text and "ABCPB1234K" not in text


def test_activate_deploy_run_approve(client):
    assert client.post("/api/agents/loanprocess/runs", json={"input": "hi"}).status_code == 409  # not activated yet
    assert client.post("/api/agents/loanprocess/activate", json={"business_name": "Demo Finance", "language": "Tamil"}).status_code == 200
    assert client.post("/api/agents/loanprocess/runs", json={"input": "hi"}).status_code == 409  # not deployed yet
    dep = go_live(client, "loanprocess")
    assert dep["status"] == "live" and dep["version"] == 1 and dep["eval"]["passed"]
    run = client.post("/api/agents/loanprocess/runs", json={"input": "Follow up on loan LN-1002"}).json()
    run = wait_run(client, run["id"])
    assert run["status"] == "waiting_approval"
    names = [s["name"] for s in run["steps"]]
    assert "get_loan_account" in names and "load_skill" in names and "send_message" in names
    pending = client.get("/api/approvals").json()
    mine = [a for a in pending if a["run_id"] == run["id"]]
    assert len(mine) == 1 and mine[0]["tool"] == "offer_settlement"
    assert not any(o["kind"] == "settlement_offer" for o in client.get("/api/outbox").json())  # nothing happened before approval
    assert client.post(f"/api/approvals/{mine[0]['id']}/decision", json={"approved": True, "note": "ok"}).status_code == 200
    run = wait_run(client, run["id"], until=("completed", "failed"))
    assert run["status"] == "completed" and run["output"]
    assert any(o["kind"] == "settlement_offer" for o in client.get("/api/outbox").json())
    assert run["cost_inr"] > 0 and run["model_calls"] >= 4
    assert client.post(f"/api/approvals/{mine[0]['id']}/decision", json={"approved": True}).status_code == 409  # cannot decide twice


def test_rejection_blocks_action(client):
    go_live(client, "returnsbot")
    run = wait_run(client, client.post("/api/agents/returnsbot/runs", json={"input": "Return ORD-3002"}).json()["id"])
    ap = [a for a in client.get("/api/approvals").json() if a["run_id"] == run["id"]][0]
    client.post(f"/api/approvals/{ap['id']}/decision", json={"approved": False, "note": "check photo first"})
    run = wait_run(client, run["id"], until=("completed", "failed"))
    assert run["status"] == "completed"
    assert not any(o["kind"] == "refund" for o in client.get("/api/outbox").json())


def test_versions_rollback_pause_and_metrics(client):
    assert go_live(client, "queryiq")["version"] == 1
    assert go_live(client, "queryiq", settings={"extra_instructions": "Always answer in one line."})["version"] == 2
    assert client.post("/api/agents/queryiq/rollback").json()["version"] == 1
    run = wait_run(client, client.post("/api/agents/queryiq/runs", json={"input": "Top categories last week?"}).json()["id"])
    assert run["status"] == "completed" and run["version"] == 1
    assert any(s["name"] == "run_sql" and s["status"] == "ok" for s in run["steps"])
    client.post("/api/agents/queryiq/pause")
    assert client.post("/api/agents/queryiq/runs", json={"input": "x"}).status_code == 409
    m = client.get("/api/metrics/overview").json()
    assert m["runs"] == 1 and m["completed"] == 1 and m["agents_live"] == 1
    assert len(client.get("/api/audit").json()) >= 5


def test_every_agent_deploys_in_simulation(client):
    for agent_id in load_catalog():
        dep = go_live(client, agent_id)
        assert dep["status"] == "live", (agent_id, dep["gate"], dep["eval"])
    assert sum(a["state"] == "live" for a in client.get("/api/catalog").json()) == 55


def test_builder_draft_and_save(client):
    d = client.post("/api/builder/draft", json={"brief": "An agent that answers GST questions from our notes"}).json()
    assert d["simulated"] and d["spec"]["id"] == "gst-helper"
    assert client.post("/api/builder/save", json={"spec": d["spec"]}).status_code == 200
    assert client.get("/api/catalog/gst-helper").status_code == 200


# ------------------------------------------------------------------ layer 2: client configuration
def test_config_is_bounded_locked_and_versioned(client):
    h = H("sri-balaji")
    assert client.get("/api/client", headers=h).json()["effective"]["lending.max_waiver_pct"] == 10
    assert client.put("/api/client", json={"policies": {"lending.max_waiver_pct": 80}}, headers=h).status_code == 422  # outside platform bounds
    assert client.put("/api/client", json={"policies": {"safety.mask_identity_numbers": False}}, headers=h).status_code == 422  # locked
    assert client.put("/api/client", json={"policies": {"made.up": 1}}, headers=h).status_code == 422  # not in the schema
    assert client.put("/api/client", json={"policies": {"lending.max_waiver_pct": 3}}, headers=H("sri-balaji", "operator")).status_code == 403
    out = client.put("/api/client", json={"policies": {"lending.max_waiver_pct": 3}, "note": "Board decision"}, headers=h).json()
    assert out["client"]["version"] == 2 and out["effective"]["lending.max_waiver_pct"] == 3
    v = client.get("/api/client/versions", headers=h).json()
    assert v[0]["version"] == 2 and v[0]["diff"][0] == {"key": "lending.max_waiver_pct", "label": "Maximum late-fee waiver", "old": 10, "new": 3}
    assert client.post("/api/client/rollback/1", headers=h).json()["client"]["version"] == 3
    assert client.get("/api/client", headers=h).json()["effective"]["lending.max_waiver_pct"] == 10
    assert client.get("/api/client", headers=H("quickcred")).json()["effective"]["lending.max_waiver_pct"] == 5  # another client is untouched


def test_config_change_changes_agent_behaviour(client):
    h = H("sri-balaji")
    client.put("/api/client", json={"policies": {"messaging.test_clock": "11:00"}}, headers=h)
    assert go_live(client, "loanprocess", h)["status"] == "live"
    run = wait_run(client, client.post("/api/agents/loanprocess/runs", json={"input": "Follow up on loan LN-1002"}, headers=h).json()["id"], headers=h)
    assert run["status"] == "waiting_approval"  # 5 percent is inside the 10 percent limit, so a human is asked
    assert any(s["kind"] == "config" and s["name"] == "lending.max_waiver_pct" and s["value"] == 10 for s in run["steps"])
    # The Owner tightens the rule. No code change, no redeploy.
    client.put("/api/client", json={"policies": {"lending.max_waiver_pct": 3}}, headers=h)
    run2 = wait_run(client, client.post("/api/agents/loanprocess/runs", json={"input": "Follow up on loan LN-1002"}, headers=h).json()["id"], headers=h)
    assert run2["status"] == "completed" and run2["config_version"] > run["config_version"]
    blocked = [s for s in run2["steps"] if s["kind"] == "guardrail" and s["name"] == "limit_check"]
    assert blocked and "limit of 3 percent" in blocked[0]["detail"]
    assert not [a for a in client.get("/api/approvals", headers=h).json() if a["run_id"] == run2["id"]]  # the approver was never bothered
    assert "refused" in run2["output"].lower()


def test_contact_hours_queue_instead_of_send(client):
    h = H("sri-balaji")
    client.put("/api/client", json={"policies": {"messaging.test_clock": "21:30"}}, headers=h)
    go_live(client, "loanprocess", h)
    run = wait_run(client, client.post("/api/agents/loanprocess/runs", json={"input": "Follow up on loan LN-1002"}, headers=h).json()["id"], headers=h)
    msg = [o for o in client.get("/api/outbox", headers=h).json() if o["kind"] == "message" and o["run_id"] == run["id"]]
    assert msg and msg[0]["status"] == "scheduled" and msg[0]["payload"]["send_at"] == "08:00"
    assert any(s["name"] == "send_message" and s["status"] == "scheduled" for s in run["steps"])


def test_refund_threshold_follows_client_config(client):
    # Same agent, same request, two clients: Aurevia allows instant refunds up to Rs 2,000, the sandbox up to Rs 1,500.
    for cid, expect in (("demo", "waiting_approval"), ("marigold", "completed")):
        h = H(cid)
        go_live(client, "returnsbot", h)
        run = wait_run(client, client.post("/api/agents/returnsbot/runs", json={"input": "I want to return order ORD-3002."}, headers=h).json()["id"], headers=h)
        assert run["status"] == expect, cid
    assert any(o["kind"] == "refund" for o in client.get("/api/outbox", headers=H("marigold")).json())
    assert not any(o["kind"] == "refund" for o in client.get("/api/outbox", headers=H("demo")).json())


def test_requirements_to_config_draft(client):
    h = H("sri-balaji")
    text = "We speak Hindi. Never offer a waiver above 4 percent. Contact customers only from 9 am to 6 pm. We also want voice calls."
    d = client.post("/api/client/requirements", json={"text": text}, headers=h).json()
    got = {p["key"]: p["proposed"] for p in d["proposed"]}
    assert got["lending.max_waiver_pct"] == 4 and got["messaging.language"] == "Hindi" and got["messaging.contact_end"] == "18:00"
    assert d["not_configurable"] and "Simulation" in d["source"]
    assert client.get("/api/client", headers=h).json()["client"]["version"] == 1  # a draft changes nothing


# ------------------------------------------------------------------ layer 3: data
def test_clients_are_isolated(client):
    go_live(client, "queryiq", H("sri-balaji"))
    wait_run(client, client.post("/api/agents/queryiq/runs", json={"input": "Top categories?"}, headers=H("sri-balaji")).json()["id"], headers=H("sri-balaji"))
    assert len(client.get("/api/runs", headers=H("sri-balaji")).json()) == 1
    for other in ("demo", "marigold"):
        assert client.get("/api/runs", headers=H(other)).json() == []
        assert client.get("/api/agents", headers=H(other)).json() == []
        assert client.get("/api/audit", headers=H(other)).json() == []
    assert client.get("/api/catalog/returnsbot", headers=H("sri-balaji")).status_code == 404  # not this client's industry
    assert client.get("/api/meta", headers=H("nobody")).status_code == 404


def test_data_gate_readiness_upload_and_lineage(client):
    h = H("quickcred")
    bp = client.get("/api/agents/loanprocess/blueprint", headers=h).json()
    assert bp["readiness"]["missing"] == ["loans"] and bp["datasets"][0]["classification"] == "Restricted"
    client.post("/api/agents/loanprocess/activate", json={}, headers=h)
    client.post("/api/agents/loanprocess/risk-acceptance", json={"note": "Accepted for pilot with approvals on."}, headers=h)
    dep = client.post("/api/agents/loanprocess/deployments", headers=h).json()
    assert dep["status"] == "blocked" and dep["eval"] is None
    assert any(c["name"] == "Required data is connected" and not c["passed"] for c in dep["gate"]["checks"])
    # A draft test run reaches the data gate and is refused there, visibly.
    run = wait_run(client, client.post("/api/agents/loanprocess/runs", json={"input": "Follow up on loan LN-1002", "draft": True}, headers=h).json()["id"], headers=h)
    assert any(s["kind"] == "data" and s["status"] == "denied" for s in run["steps"])
    # Upload the client's own loan book. Bad rows are rejected and reported.
    assert client.post("/api/data/loans/upload", json={"text": "loan_id,customer\nX,Y\n"}, headers=h).status_code == 422  # missing columns
    assert client.post("/api/data/loans/upload", json={"text": "x"}, headers=H("quickcred", "auditor")).status_code == 403
    q = client.post("/api/data/loans/upload", json={"text": (HERE / "sample_data" / "quickcred_loans.csv").read_text(encoding="utf-8")}, headers=h).json()
    assert q["rows_in_file"] == 8 and q["rows_accepted"] == 5 and q["rows_rejected"] == 3
    inv = {d["name"]: d for d in client.get("/api/data", headers=h).json()}
    assert inv["loans"]["status"] == "upload" and inv["loans"]["rows"] == 5 and "LoanProcess" in inv["loans"]["agents"]
    assert client.post("/api/agents/loanprocess/deployments", headers=h).json()["status"] == "live"
    # Lumora now reads ITS loans; Northvale still reads the sample book.
    with as_client("quickcred"):
        assert REGISTRY["get_loan_account"]("QC-2001")["customer"] == "Pooja Verma"
        assert REGISTRY["get_loan_account"]("LN-1002")["status"] == "error"
    with as_client("sri-balaji"):
        assert REGISTRY["get_loan_account"]("QC-2001")["status"] == "error"
        assert REGISTRY["get_loan_account"]("LN-1002")["customer"] == "Kavitha S"
    detail = client.get("/api/data/loans", headers=h).json()
    assert "••• hidden" in detail["sample"]["rows"][0] and "Pooja Verma" not in str(detail["sample"])
    assert any(a["dataset"] == "loans" and a["status"] == "denied" for a in client.get("/api/data/access", headers=h).json())


def test_trace_shows_every_layer(client):
    h = H("sri-balaji")
    client.put("/api/client", json={"policies": {"messaging.test_clock": "11:00"}}, headers=h)
    go_live(client, "loanprocess", h)
    run = wait_run(client, client.post("/api/agents/loanprocess/runs", json={"input": "Follow up on loan LN-1002. My Aadhaar is 1234 5678 9012."}, headers=h).json()["id"], headers=h)
    layers = {s["layer"] for s in run["steps"]}
    assert layers == {2, 3, 4, 5}, layers
    assert "1234 5678 9012" not in str(run)  # masked before the model, the trace and the stored input
    data_step = next(s for s in run["steps"] if s["kind"] == "data")
    assert data_step["name"] == "loans" and data_step["classification"] == "Restricted" and data_step["by"] == "get_loan_account"
    assert "90000-01002" not in str([s.get("output") for s in run["steps"]])  # contact details masked in stored previews


# ------------------------------------------------------------------ layer 5: safety, security, governance
def test_roles_are_enforced(client):
    h = H("sri-balaji")
    assert client.post("/api/agents/queryiq/activate", json={}, headers=H("sri-balaji", "auditor")).status_code == 403
    assert client.post("/api/agents/queryiq/activate", json={}, headers=H("sri-balaji", "approver")).status_code == 403
    assert client.post("/api/agents/queryiq/activate", json={}, headers=H("sri-balaji", "operator")).status_code == 200
    assert client.post("/api/governance/kill", json={"engaged": True, "reason": "testing"}, headers=H("sri-balaji", "operator")).status_code == 403
    assert client.get("/api/governance/evidence", headers=H("sri-balaji", "operator")).status_code == 403
    assert client.get("/api/governance/evidence", headers=H("sri-balaji", "auditor")).status_code == 200
    assert client.get("/api/runs", headers=H("sri-balaji", "auditor")).status_code == 200  # auditors can read everything
    assert client.get("/api/meta", headers=H("sri-balaji", "hacker")).status_code == 400
    assert h


def test_high_risk_needs_named_owner(client):
    h = H("sri-balaji")
    client.post("/api/agents/loanprocess/activate", json={}, headers=h)
    dep = client.post("/api/agents/loanprocess/deployments", headers=h).json()
    assert dep["status"] == "blocked" and dep["risk"] == "High"
    assert client.post("/api/agents/loanprocess/risk-acceptance", json={"note": "Looks fine to me, go ahead."}, headers=H("sri-balaji", "operator")).status_code == 403
    assert client.post("/api/agents/loanprocess/risk-acceptance", json={"note": "ok"}, headers=h).status_code == 422
    client.post("/api/agents/loanprocess/risk-acceptance", json={"note": "Waivers capped at 10 percent and always approved by a supervisor."}, headers=h)
    dep = client.post("/api/agents/loanprocess/deployments", headers=h).json()
    assert dep["status"] == "live" and dep["gate"]["passed"] and len(dep["gate"]["checks"]) == 6


def test_four_eyes_rule(client):
    owner, approver = H("quickcred"), H("quickcred", "approver")
    client.post("/api/data/loans/connect", json={"mode": "sample"}, headers=owner)
    go_live(client, "loanprocess", owner)
    run = wait_run(client, client.post("/api/agents/loanprocess/runs", json={"input": "Follow up on loan LN-1002"}, headers=owner).json()["id"], headers=owner)
    ap = [a for a in client.get("/api/approvals", headers=owner).json() if a["run_id"] == run["id"]][0]
    assert ap["tool"] == "send_message" and ap["why"] == "Added by this client"  # Lumora approves every outbound message
    r = client.post(f"/api/approvals/{ap['id']}/decision", json={"approved": True}, headers=owner)
    assert r.status_code == 403 and "Four-eyes" in r.json()["detail"]
    assert client.post(f"/api/approvals/{ap['id']}/decision", json={"approved": True}, headers=approver).status_code == 200


def test_emergency_stop(client):
    h = H("sri-balaji")
    client.put("/api/client", json={"policies": {"messaging.test_clock": "11:00"}}, headers=h)
    go_live(client, "loanprocess", h)
    run = wait_run(client, client.post("/api/agents/loanprocess/runs", json={"input": "Follow up on loan LN-1002"}, headers=h).json()["id"], headers=h)
    assert run["status"] == "waiting_approval"
    out = client.post("/api/governance/kill", json={"engaged": True, "reason": "Wrong message template went out"}, headers=H("sri-balaji", "approver")).json()
    assert out["engaged"] and out["approvals_cancelled"] == 1
    assert client.get(f"/api/runs/{run['id']}", headers=h).json()["status"] == "stopped"
    assert client.post("/api/agents/loanprocess/runs", json={"input": "x"}, headers=h).status_code == 423
    assert client.post("/api/agents/loanprocess/deployments", headers=h).json()["status"] == "blocked"
    assert client.post("/api/agents/loanprocess/runs", json={"input": "x"}, headers=H("demo")).status_code == 409  # other clients are not stopped (409 = not activated)
    assert any(i["kind"] == "emergency_stop" for i in client.get("/api/governance/incidents", headers=h).json())
    client.post("/api/governance/kill", json={"engaged": False}, headers=h)
    assert client.post("/api/agents/loanprocess/runs", json={"input": "Follow up on loan LN-1002"}, headers=h).status_code == 200


def test_untrusted_text_is_neutralised(client):
    h = H("marigold")
    go_live(client, "reviewmine", h)
    run = wait_run(client, client.post("/api/agents/reviewmine/runs", json={"input": "What are customers saying about SKU-501?"}, headers=h).json()["id"], headers=h)
    tool = next(s for s in run["steps"] if s["name"] == "get_reviews")
    assert "ignore all previous instructions" not in tool["output"].lower() and "removed by the platform" in tool["output"]
    assert any(s["name"] == "untrusted_text_removed" for s in run["steps"])
    inc = client.get("/api/governance/incidents", headers=h).json()
    assert any(i["kind"] == "prompt_injection" for i in inc)
    assert client.post(f"/api/governance/incidents/{inc[0]['id']}/close", json={"note": "Review hidden from catalogue."}, headers=h).json()["status"] == "closed"


def test_selftest_and_audit_chain(client):
    for cid in ("demo", "sri-balaji", "quickcred", "marigold", "carepoint", "kaveri"):
        st = client.post("/api/governance/selftest", headers=H(cid, "auditor")).json()
        assert st["passed"] == st["total"] and st["total"] >= 16, (cid, [r for r in st["results"] if not r["passed"]])
        assert client.get("/api/outbox", headers=H(cid)).json() == []  # a dry run performs no action
    h = H("sri-balaji")
    go_live(client, "queryiq", h)
    assert client.get("/api/audit/verify", headers=h).json()["intact"]
    with as_client("sri-balaji"):  # tamper with one past record directly in the store
        rec = get_store().list("audit", order_by="seq", descending=False)[1]
        get_store().update("audit", rec["id"], {"actor": "someone-else"})
    v = client.get("/api/audit/verify", headers=h).json()
    assert not v["intact"] and v["broken_at_seq"] == rec["seq"]


def test_evidence_pack(client):
    h = H("sri-balaji")
    client.put("/api/client", json={"policies": {"lending.max_waiver_pct": 8}, "note": "Risk committee"}, headers=h)
    go_live(client, "loanprocess", h)
    pack = client.get("/api/governance/evidence", headers=H("sri-balaji", "auditor")).json()
    assert pack["client"]["id"] == "sri-balaji" and len(pack["sha256"]) == 64
    assert pack["configuration"]["effective_settings"]["lending.max_waiver_pct"] == 8 and len(pack["configuration"]["history"]) >= 2
    agent = pack["agents"][0]
    assert agent["risk"]["tier"] == "High" and agent["risk_acceptance"]["by"] and agent["datasets"] == ["loans"]
    assert len(pack["controls"]) == 25 and pack["audit"]["verification"]["intact"]


# ------------------------------------------------------------------ layer 1: the console is served and knows who is looking
def test_console_and_meta(client):
    assert "DigiQuench" in client.get("/").text
    m = client.get("/api/meta", headers=H("quickcred", "approver")).json()
    assert m["client"]["name"] == "Lumora Credit" and m["role"] == "approver"
    assert "approval.decide" in m["permissions"] and "config.edit" not in m["permissions"]
    assert len(client.get("/api/clients").json()) == 6
    assert [layer["layer"] for layer in client.get("/api/layers", headers=H("quickcred")).json()] == [1, 2, 3, 4, 5]
    assert {a["vertical"] for a in client.get("/api/catalog", headers=H("quickcred")).json()} == {"Fintech"}


# ------------------------------------------------------------------ sign-in and roles
def test_sign_in_and_signed_sessions(client, monkeypatch):
    from dq import config  # noqa: PLC0415

    monkeypatch.setattr(config, "AUTH_MODE", "token")
    assert client.get("/api/meta").status_code == 401  # not signed in
    demo = client.get("/api/auth/demo-users?client=kaveri").json()
    assert {u["role"] for u in demo["users"]} == {"owner", "operator", "approver", "technician", "auditor"}
    assert client.post("/api/auth/login", json={"client": "kaveri", "username": "plant.head", "password": "wrong"}).status_code == 401
    out = client.post("/api/auth/login", json={"client": "kaveri", "username": "tech.mech", "password": "DOS@2026"}).json()
    tok = {"Authorization": "Bearer " + out["token"]}
    me = client.get("/api/meta", headers=tok).json()
    assert me["role"] == "technician" and me["client"]["id"] == "kaveri" and me["user"]["technician_id"] == "TEC-11"
    # Headers cannot override a signed token, and a tampered token is refused.
    me2 = client.get("/api/meta", headers={**tok, "X-DQ-Role": "owner", "X-DQ-Client": "sri-balaji"}).json()
    assert me2["role"] == "technician" and me2["client"]["id"] == "kaveri"
    body, sig = out["token"].split(".")
    assert client.get("/api/meta", headers={"Authorization": "Bearer " + body + "." + sig[::-1]}).status_code == 401
    assert client.post("/api/agents/machinewatch/activate", json={}, headers=tok).status_code == 403  # technicians do not configure agents
    # A user of one company cannot sign in to another.
    assert client.post("/api/auth/login", json={"client": "sri-balaji", "username": "tech.mech", "password": "DOS@2026"}).status_code == 401


# ------------------------------------------------------------------ manufacturing: the live plant
MFG = ["machinewatch", "rootcauseiq", "fixdispatch", "sparesense", "plansync", "lottrace"]
K = H("kaveri")


def _plant_ready(client):
    for a in MFG:
        assert go_live(client, a, K)["status"] == "live", a


def _alarm(machine, fault):
    from dq import plant  # noqa: PLC0415

    with as_client("kaveri"):
        pl = plant.get_plant("kaveri")
        pl.inject(machine, fault)
        for _ in range(40):
            events = [e for e in pl.tick(confirm=3) if e["machine"] == machine]
            if events:
                return plant.create_incident(events[0], pl)
    raise AssertionError("alarm not detected")


def test_every_fault_is_detected_and_diagnosed(client):
    from dq import plant  # noqa: PLC0415

    cases = [("LTH-101", "spindle_bearing_wear"), ("LTH-102", "coolant_pump_failure"), ("VMC-201", "cutting_tool_wear"), ("VMC-202", "servo_motor_overload"),
             ("PRS-501", "hydraulic_leak"), ("HTF-401", "inductor_coil_degradation"), ("CMP-601", "air_filter_clogged")]
    with as_client("kaveri"):
        for machine, fault in cases:
            pl = plant.get_plant("kaveri")
            pl.inject(machine, fault)
            hit = None
            for i in range(40):
                if [e for e in pl.tick(confirm=3) if e["machine"] == machine]:
                    hit = i
                    break
            assert hit is not None and (hit + 1) * 2 <= 60, (machine, fault)  # detected within a minute
            assert REGISTRY["rank_root_causes"](machine)["causes"][0]["cause"] == fault, (machine, fault)
            pl.clear(machine)
        # Agents see telemetry, never the injected fault.
        assert "simulated_fault" not in str(REGISTRY["get_machine_status"]("LTH-101"))


def test_downtime_response_chain_and_learning(client):
    import asyncio  # noqa: PLC0415

    from dq import plant, response  # noqa: PLC0415

    _plant_ready(client)
    with as_client("kaveri"):
        assert not get_store().list("work_orders"), "evaluation runs must not create work orders"
    inc = _alarm("LTH-101", "spindle_bearing_wear")
    asyncio.run(response.respond(client.app.state.manager, "kaveri", inc))
    with as_client("kaveri"):
        inc = get_store().get("plant_incidents", inc["id"])
    assert inc["root_cause"] == "Spindle front bearing wear" and inc["confidence"] >= 0.5
    assert inc["technician"] == "Senior Technician (Mechanical)" and inc["work_order"]
    assert [r["agent_id"] for r in inc["runs"]] == MFG
    pending = {a["tool"]: a for a in client.get("/api/approvals", headers=K).json()}
    assert "order_spare_part" in pending and "Rs 25,000" in pending["order_spare_part"]["why"]  # 38,500 > limit
    assert "hold_lot" in pending
    moved = [o for o in client.get("/api/outbox", headers=K).json() if o["kind"] == "order_moved"]
    assert moved and moved[0]["payload"]["to"] == "LTH-102"
    # The technician works the order; another technician cannot touch it.
    tech, other = H("kaveri", "technician"), H("kaveri", "technician")
    tech["X-DQ-Technician"], other["X-DQ-Technician"] = "TEC-11", "TEC-12"
    wo = client.get("/api/workorders", headers=tech).json()[0]
    assert client.get("/api/workorders", headers=other).json() == []
    assert client.post(f"/api/workorders/{wo['id']}/ack", json={}, headers=other).status_code == 403
    assert client.post(f"/api/workorders/{wo['id']}/resolve", json={}, headers=tech).status_code == 409  # must acknowledge and start first
    for action, body in (("ack", {}), ("start", {}), ("resolve", {"notes": "Bearing pitted, replaced", "confirmed_cause": "spindle_bearing_wear", "minutes": 90})):
        assert client.post(f"/api/workorders/{wo['id']}/{action}", json=body, headers=tech).status_code == 200
    state = client.get("/api/plant/state", headers=K).json()
    assert next(m for m in state["machines"] if m["machine_id"] == "LTH-101")["status"] == "running"
    with as_client("kaveri"):
        assert len(plant.learned_repairs()) == 1  # the confirmed cause now counts as evidence next time
    assert client.get("/api/plant/state", headers=H("kaveri", "technician")).json()["faults"] == {}  # only demo roles see the simulator


def test_unacknowledged_work_order_escalates(client):
    import asyncio  # noqa: PLC0415

    from dq import response  # noqa: PLC0415

    _plant_ready(client)
    client.put("/api/client", json={"policies": {"manufacturing.ack_minutes": 1}}, headers=K)
    inc = _alarm("PRS-501", "hydraulic_leak")
    asyncio.run(response.respond(client.app.state.manager, "kaveri", inc))
    with as_client("kaveri"):
        wo = get_store().list("work_orders")[0]
        assert wo["technician_name"] in ("Senior Technician (Mechanical)", "Senior Technician (Electrical)")  # hydraulic skill
        get_store().update("work_orders", wo["id"], {"assigned_at": wo["assigned_at"] - 120})
        asyncio.run(response.check_escalations("kaveri"))
        assert get_store().get("work_orders", wo["id"])["escalated"]
    assert any(i["kind"] == "work_order_not_acknowledged" for i in client.get("/api/governance/incidents", headers=K).json())


def test_spare_order_limit_follows_config_and_auto_response_switch(client):
    import asyncio  # noqa: PLC0415

    from dq import response  # noqa: PLC0415

    _plant_ready(client)
    client.put("/api/client", json={"policies": {"manufacturing.spare_auto_limit_inr": 50000}}, headers=K)
    inc = _alarm("LTH-101", "spindle_bearing_wear")
    asyncio.run(response.respond(client.app.state.manager, "kaveri", inc))
    assert not [a for a in client.get("/api/approvals", headers=K).json() if a["tool"] == "order_spare_part"]  # 38,500 < 50,000
    assert any(o["kind"] == "spare_order" for o in client.get("/api/outbox", headers=K).json())
    client.put("/api/client", json={"policies": {"manufacturing.auto_response": False}}, headers=K)
    inc2 = _alarm("PRS-501", "hydraulic_leak")
    asyncio.run(response.respond(client.app.state.manager, "kaveri", inc2))
    with as_client("kaveri"):
        assert not get_store().get("plant_incidents", inc2["id"]).get("runs")
    # Machine control is a locked platform rule.
    assert client.put("/api/client", json={"policies": {"manufacturing.machines_read_only": False}}, headers=K).status_code == 422


def test_fault_simulation_is_role_limited(client):
    assert client.post("/api/plant/faults", json={"machine": "LTH-101", "fault": "spindle_bearing_wear"}, headers=H("kaveri", "auditor")).status_code == 403
    assert client.post("/api/plant/faults", json={"machine": "PRS-501", "fault": "spindle_bearing_wear"}, headers=K).status_code == 422  # not for a press
    assert client.post("/api/plant/faults", json={"machine": "LTH-101", "fault": "spindle_bearing_wear"}, headers=K).status_code == 200
    assert client.get("/api/plant/state", headers=H("sri-balaji")).status_code == 404  # a lender has no plant


def test_designated_approver_rule():
    """Axion names the Quality Head as the only person who may hold a lot (segregation of duties)."""
    from dq import auth
    from dq.clients import as_client
    with as_client("kaveri"):
        named = [u["username"] for u in auth.designated_approvers("hold_lot")]
        assert named == ["quality.head"]
        assert [u["username"] for u in auth.designated_approvers("order_spare_part")] == ["maint.head"]
        assert auth.designated_approvers("issue_refund") == []


def test_voice_agents_build_offline_with_safe_tools():
    """The two Live API agents build without a network call, and the technician assistant has no tool that orders,
    holds or changes anything except creating a task."""
    import importlib  # noqa: PLC0415
    import sys  # noqa: PLC0415
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    fix = importlib.import_module("adk_agents.fixassist_voice.agent").root_agent
    names = {t.__name__ for t in fix.tools}
    assert names == {"get_machine_status", "rank_root_causes", "search_repair_history", "search_manuals", "create_task"}
    assert not names & {"order_spare_part", "hold_lot", "create_work_order", "reassign_order"}


def test_repair_search_falls_back_to_keywords_without_a_key(monkeypatch):
    from dq import config  # noqa: PLC0415
    monkeypatch.setattr(config, "EMBED_SEARCH", True)
    with as_client("kaveri"):
        res = REGISTRY["search_repair_history"]("cnc_lathe", "vibration high noise")
    assert res["cases"] and res.get("method") != "embeddings"  # mock mode: keyword search
