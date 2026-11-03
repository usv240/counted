"""Let Counted's ECS task role write trace spans to CloudWatch (X-Ray OTLP endpoint). Run once, then redeploy.

    uv run python deploy/enable_tracing.py
    uv run python deploy/ecs_redeploy.py

Changes only the inline policy `counted-runtime` on `countedTaskRole` (Counted's own role): adds one statement, `Traces`.
Re-running it replaces that statement, nothing else. CloudWatch Transaction Search must already be on in the account.
"""

from __future__ import annotations

import json

import boto3

ROLE, POLICY = "countedTaskRole", "counted-runtime"
TRACES = {
    "Sid": "Traces",
    "Effect": "Allow",
    "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets",
               "xray:PutSpans", "xray:PutSpansForIndexing"],
    "Resource": "*",
}


def main() -> None:
    iam = boto3.client("iam")
    doc = iam.get_role_policy(RoleName=ROLE, PolicyName=POLICY)["PolicyDocument"]
    doc["Statement"] = [s for s in doc["Statement"] if s.get("Sid") != "Traces"] + [TRACES]
    iam.put_role_policy(RoleName=ROLE, PolicyName=POLICY, PolicyDocument=json.dumps(doc))
    destination = boto3.client("xray").get_trace_segment_destination()
    print("statements:", [s.get("Sid") for s in doc["Statement"]])
    print("Transaction Search:", destination["Destination"], destination["Status"])


if __name__ == "__main__":
    main()
