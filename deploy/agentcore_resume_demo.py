"""Resume demo: a family stops mid-interview and comes back, served by a different AgentCore microVM each time.

    uv run python deploy/agentcore_resume_demo.py

Invokes the deployed runtime only (no deploy, no changes). Two runtime sessions mean two separate microVMs; the second
knows nothing except what AgentCore Memory gives back, and still reaches the panel's finding without re-asking.
"""

from __future__ import annotations

import json
import textwrap
import time
import uuid

import boto3

REGION = "us-east-1"
ctl = boto3.client("bedrock-agentcore-control", region_name=REGION)
data = boto3.client("bedrock-agentcore", region_name=REGION)
ARN = next(r["agentRuntimeArn"] for r in ctl.list_agent_runtimes()["agentRuntimes"] if r["agentRuntimeName"] == "counted_interviewer")


def turn(microvm: str, case: str, message: str) -> dict:
    t = time.time()
    res = data.invoke_agent_runtime(agentRuntimeArn=ARN, runtimeSessionId=microvm, qualifier="DEFAULT",
                                    payload=json.dumps({"action": "interview", "session_id": case, "consent": True,
                                                        "message": message}).encode())
    out = json.loads(res["response"].read())
    out["seconds"] = time.time() - t
    return out


def show(title: str, said: str, r: dict) -> None:
    print(f"\n=== {title} ({r['seconds']:.0f} s, build {r.get('build')}) ===")
    print("Family :", textwrap.fill(said, 100, subsequent_indent="         "))
    print("Counted:", textwrap.fill(r["reply"].split("\n\n")[0] if "\n\n" in r["reply"] else r["reply"], 100,
                                    subsequent_indent="         "))


case = f"family-{uuid.uuid4().hex[:6]}"
first_vm, second_vm = str(uuid.uuid4()) + "-monday", str(uuid.uuid4()) + "-thursday"
print("AgentCore Runtime:", ARN.split("/")[-1], "| family case:", case)

said = ("My mother died after the February 2021 freeze. She was 78, lived in Houston, Texas, and died at home on "
        "2021-02-17. Her oxygen machine stopped when the power went out.")
r1 = turn(first_vm, case, said)
show("Monday, microVM 1", said, r1)
print("Case file after Monday:", len(r1["facts"]["evidence"]), "circumstance on record. The family closes the tab.")

said = "Sorry, I had to stop. That's everything I know."
r2 = turn(second_vm, case, said)
show("Thursday, a brand-new microVM 2", said, r2)
if not r2.get("determination"):  # the interviewer may first check the family has nothing to add; answer it
    said = "No, nothing else."
    r2 = turn(second_vm, case, said)
    print("Family :", said)
    print("Counted:", textwrap.fill(r2["reply"].split("\n\n")[0], 100, subsequent_indent="         "))
d = r2.get("determination") or {}
print("Case file rebuilt from AgentCore Memory:", len(r2["facts"]["evidence"]), "circumstance;",
      "panel finding:", d.get("label"), "-", (d.get("mechanism") or "").replace("_", " "))
