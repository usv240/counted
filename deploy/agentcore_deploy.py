"""Deploy Counted's interviewer to Amazon Bedrock AgentCore Runtime with AgentCore Memory, then prove resume works.

    uv run python deploy/agentcore_package.py     # build the arm64 package (no AWS calls)
    uv run python deploy/agentcore_deploy.py      # create or update the resources below, then test

Creates, in us-east-1, all named for Counted and tagged project=counted:
  - S3 object  s3://counted-agentcore-<account>/counted_interviewer/counted_agentcore.zip  (the code package)
  - IAM role   countedAgentCoreRole: trusted by bedrock-agentcore.amazonaws.com in this account only; may write its
               own logs and traces, invoke Bedrock models, geocode with Amazon Location, read the package, and use
               only the counted_interviews memory
  - Memory     counted_interviews: short-term events only, expire after 30 days
  - Runtime    counted_interviewer: Python 3.12 direct code deploy, public network, COUNTED_MEMORY_ID set

The test then runs one interview turn in one runtime session, and a second turn in a NEW runtime session (a fresh
microVM): the conversation must come back from Memory and the case file must be rebuilt from it.

Teardown: delete the runtime, the memory, the role and its inline policy, and the bucket.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid

from pathlib import Path

import boto3

REGION = "us-east-1"
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
BUCKET = f"counted-agentcore-{ACCOUNT}"
KEY = "counted_interviewer/counted_agentcore.zip"
ROLE = "countedAgentCoreRole"
MEMORY = "counted_interviews"
RUNTIME = "counted_interviewer"

iam = boto3.client("iam")
s3 = boto3.client("s3", region_name=REGION)
ctl = boto3.client("bedrock-agentcore-control", region_name=REGION)
data = boto3.client("bedrock-agentcore", region_name=REGION)


def ensure_memory() -> dict:
    for m in ctl.list_memories().get("memories", []):
        if m["id"].startswith(MEMORY + "-"):
            return ctl.get_memory(memoryId=m["id"])["memory"]
    m = ctl.create_memory(name=MEMORY, eventExpiryDuration=30, tags={"project": "counted"},
                          description="Counted: lets a family pause an interview and resume later (30-day expiry).")["memory"]
    while m["status"] != "ACTIVE":
        time.sleep(10)
        m = ctl.get_memory(memoryId=m["id"])["memory"]
    return m


def ensure_role(memory_arn: str) -> str:
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "bedrock-agentcore.amazonaws.com"}, "Action": "sts:AssumeRole",
        "Condition": {"StringEquals": {"aws:SourceAccount": ACCOUNT},
                      "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:*"}}}]}
    runtime_logs = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/bedrock-agentcore/runtimes/"
    policy = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"], "Resource": runtime_logs + "*"},
        {"Effect": "Allow", "Action": ["logs:DescribeLogGroups"], "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:*"},
        {"Effect": "Allow", "Action": ["logs:CreateLogStream", "logs:PutLogEvents"], "Resource": runtime_logs + "*:log-stream:*"},
        {"Effect": "Allow", "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules",
                                       "xray:GetSamplingTargets", "xray:PutSpans", "xray:PutSpansForIndexing"], "Resource": "*"},
        {"Effect": "Allow", "Action": "cloudwatch:PutMetricData", "Resource": "*",
         "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}}},
        {"Effect": "Allow", "Action": ["bedrock-agentcore:GetWorkloadAccessToken", "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                                       "bedrock-agentcore:GetWorkloadAccessTokenForUserId"],
         "Resource": [f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:workload-identity-directory/default",
                      f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:workload-identity-directory/default/workload-identity/{RUNTIME}-*"]},
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
         "Resource": ["arn:aws:bedrock:*::foundation-model/*", f"arn:aws:bedrock:*:{ACCOUNT}:inference-profile/*"]},
        {"Effect": "Allow", "Action": ["geo-places:Geocode"], "Resource": f"arn:aws:geo-places:{REGION}::provider/default"},
        {"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": f"arn:aws:s3:::{BUCKET}/{KEY}"},
        {"Effect": "Allow", "Action": ["bedrock-agentcore:CreateEvent", "bedrock-agentcore:ListEvents", "bedrock-agentcore:GetEvent",
                                       "bedrock-agentcore:ListSessions", "bedrock-agentcore:GetMemory"], "Resource": memory_arn},
    ]}
    try:
        arn = iam.get_role(RoleName=ROLE)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(RoleName=ROLE, AssumeRolePolicyDocument=json.dumps(trust),
                              Description="Counted interviewer on AgentCore Runtime", Tags=[{"Key": "project", "Value": "counted"}])["Role"]["Arn"]
        time.sleep(15)  # let the new role propagate before AgentCore assumes it
    iam.put_role_policy(RoleName=ROLE, PolicyName="counted-agentcore", PolicyDocument=json.dumps(policy))
    return arn


def ensure_runtime(role_arn: str, memory_id: str) -> str:
    artifact = {"codeConfiguration": {"code": {"s3": {"bucket": BUCKET, "prefix": KEY}},
                                      "runtime": "PYTHON_3_12", "entryPoint": ["main.py"]}}
    # AgentCore Observability: main.py starts ADOT, which traces every invocation (agent, Graph, model and tool spans).
    # Log export is off, so prompts and the family's words stay out of CloudWatch, as on ECS.
    env = {"COUNTED_MEMORY_ID": memory_id, "AWS_REGION": REGION, "COUNTED_STEERING": "1",
           "AGENT_OBSERVABILITY_ENABLED": "true", "OTEL_PYTHON_DISTRO": "aws_distro",
           "OTEL_PYTHON_CONFIGURATOR": "aws_configurator", "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
           "OTEL_TRACES_EXPORTER": "otlp", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"https://xray.{REGION}.amazonaws.com/v1/traces",
           "OTEL_LOGS_EXPORTER": "none", "OTEL_METRICS_EXPORTER": "none"}
    existing = [r for r in ctl.list_agent_runtimes().get("agentRuntimes", []) if r["agentRuntimeName"] == RUNTIME]
    if existing:
        rid = existing[0]["agentRuntimeId"]
        ctl.update_agent_runtime(agentRuntimeId=rid, agentRuntimeArtifact=artifact, roleArn=role_arn,
                                 networkConfiguration={"networkMode": "PUBLIC"}, environmentVariables=env)
    else:
        rid = ctl.create_agent_runtime(agentRuntimeName=RUNTIME, agentRuntimeArtifact=artifact, roleArn=role_arn,
                                       networkConfiguration={"networkMode": "PUBLIC"}, environmentVariables=env,
                                       description="Counted: disaster-death interviewer (Strands)",
                                       tags={"project": "counted"})["agentRuntimeId"]
    while True:
        r = ctl.get_agent_runtime(agentRuntimeId=rid)
        if r["status"] in ("READY", "CREATE_FAILED", "UPDATE_FAILED"):
            break
        time.sleep(10)
    if r["status"] != "READY":
        sys.exit(f"runtime {r['status']}: {r.get('failureReason')}")
    return r["agentRuntimeArn"]


def invoke(arn: str, runtime_session: str, payload: dict) -> dict:
    res = data.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId=runtime_session, qualifier="DEFAULT",
                                    payload=json.dumps(payload).encode())
    return json.loads(res["response"].read())


def resume_test(arn: str) -> None:
    case = f"resume-{uuid.uuid4().hex[:10]}"
    first, second = str(uuid.uuid4()) + "-a", str(uuid.uuid4()) + "-b"  # two runtime sessions = two microVMs
    r1 = invoke(arn, first, {"action": "interview", "session_id": case, "consent": True, "message":
                "My mother died after the February 2021 freeze. She was 78 and lived in Houston, Texas, and she died at "
                "home on 2021-02-17. She used a home oxygen machine and it stopped when the power went out."})
    print("build on the runtime:", r1.get("build"))
    print("session 1 reply:", r1["reply"][:200])
    print("session 1 facts on file:", len(r1["facts"]["evidence"]), "circumstance(s)")
    r2 = invoke(arn, second, {"action": "interview", "session_id": case, "consent": True, "message":
                "Sorry, I had to stop yesterday. That's everything I know."})
    print("session 2 (new microVM) reply:", r2["reply"][:300])
    print("session 2 facts rebuilt from Memory:", len(r2["facts"]["evidence"]), "circumstance(s);",
          "determination:", (r2.get("determination") or {}).get("label"))


def build_and_upload() -> None:
    """Package the current commit and upload it, so the runtime never runs stale code."""
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "deploy/agentcore_package.py")], check=True, cwd=root)
    s3.upload_file(str(root / "build/agentcore/counted_agentcore.zip"), BUCKET, KEY, ExtraArgs={"ExpectedBucketOwner": ACCOUNT})
    print("uploaded package for", (root / "build/agentcore/package/BUILD.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    build_and_upload()
    memory = ensure_memory()
    role = ensure_role(memory["arn"])
    runtime = ensure_runtime(role, memory["id"])
    print("runtime:", runtime, "| memory:", memory["id"])
    resume_test(runtime)
