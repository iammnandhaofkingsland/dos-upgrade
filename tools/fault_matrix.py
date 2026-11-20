"""Fault matrix: injects every fault on every machine type it applies to, over several random seeds, and reports
detection time and whether RootCauseIQ's ranking put the true cause first. Runs offline in a few seconds.
Usage: cd server && PYTHONPATH=. python ../tools/fault_matrix.py"""
import os

os.environ.setdefault("DQ_MODEL_MODE", "mock")
os.environ.setdefault("DQ_PLANT_LOOP", "0")

from dq import plant, sample_data as D  # noqa: E402
from dq.clients import as_client  # noqa: E402
from dq.context import run_var  # noqa: E402
from dq.tools import manufacturing as M  # noqa: E402

SEEDS = (7, 11, 23, 42, 99, 5, 13, 17, 31, 77)
run_var.set({"run_id": "fault-matrix", "agent_id": "rootcauseiq", "tool": None, "seen": set(), "quiet": True, "dry_run": True})
by_type: dict[str, list[str]] = {}
for mid, m in D.MACHINES.items():
    by_type.setdefault(m["type"], []).append(mid)
times, correct, total = [], 0, 0
print(f"{'fault':28s} {'machine':8s} {'detected after (s)':34s} {'top cause right':16s} confidence")
with as_client("kaveri"):
    for fault, sig in D.FAULT_SIGNATURES.items():
        for mtype in sig["types"]:
            for mid in by_type.get(mtype, []):
                hits, rights, conf = [], 0, 0.0
                for seed in SEEDS:
                    pl = plant.Plant("kaveri", seed=seed)
                    pl.tick(5)
                    pl.inject(mid, fault)
                    hit = next(((i + 1) * plant.TICK_SECONDS for i in range(60) if [e for e in pl.tick(confirm=3) if e["machine"] == mid]), None)
                    plant._plants["kaveri"] = pl
                    top = M.rank_root_causes(mid)["causes"][0]
                    hits.append(hit); rights += top["cause"] == fault; conf = top["confidence"]
                times += [h for h in hits if h is not None]; correct += rights; total += len(SEEDS)
                print(f"{fault:28s} {mid:8s} {str(hits):34s} {rights}/{len(SEEDS):<14d} {conf}")
print(f"\n{total} runs: detected {len(times)}, in {min(times)} to {max(times)} s; top cause correct in {correct} of {total}.")
