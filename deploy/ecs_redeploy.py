"""Build the image, push it to ECR tagged with the git short SHA, and roll the live ECS Express service onto it.

    uv run python deploy/ecs_redeploy.py

ECS Express replaces the whole primary container on update, so the current container settings (port, logs,
environment) are read back from the service and resent with only the image changed. Roll-out takes 5-8 minutes;
the script waits until the public URL serves the new image's /v1/health.
"""

from __future__ import annotations

import base64
import subprocess
import time
from pathlib import Path

import boto3
import httpx

REGION = "us-east-1"
SERVICE = "arn:aws:ecs:us-east-1:957325809861:service/counted/counted"
REPO = "counted"
URL = "https://co-435ce50e27c4441da1f6e8104db5cb23.ecs.us-east-1.on.aws"
ROOT = Path(__file__).resolve().parents[1]


def run(*cmd: str, **kw) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=ROOT, **kw).stdout.strip()


def main() -> None:
    tag = run("git", "rev-parse", "--short", "HEAD")
    if run("git", "status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("commit first: the image tag must name the code inside it")
    ecr = boto3.client("ecr", region_name=REGION)
    auth = ecr.get_authorization_token()["authorizationData"][0]
    registry = auth["proxyEndpoint"].removeprefix("https://")
    user, password = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    image = f"{registry}/{REPO}:{tag}"
    subprocess.run(["docker", "login", "--username", user, "--password-stdin", registry], input=password, text=True,
                   check=True, cwd=ROOT, capture_output=True)
    subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", image, "."], check=True, cwd=ROOT)
    subprocess.run(["docker", "push", image], check=True, cwd=ROOT)

    ecs = boto3.client("ecs", region_name=REGION)
    current = ecs.describe_express_gateway_service(serviceArn=SERVICE)["service"]["activeConfigurations"][0]
    container = {k: v for k, v in current["primaryContainer"].items()
                 if k in ("containerPort", "awsLogsConfiguration", "command", "environment", "secrets")}
    ecs.update_express_gateway_service(serviceArn=SERVICE, primaryContainer={**container, "image": image})
    print(f"rolling out {image}", flush=True)

    for _ in range(80):
        time.sleep(15)
        try:
            served = ecs.describe_express_gateway_service(serviceArn=SERVICE)["service"]["activeConfigurations"]
            if len(served) == 1 and served[0]["primaryContainer"]["image"] == image and \
                    httpx.get(f"{URL}/v1/health", timeout=15).status_code == 200:
                print("live:", image)
                return
        except httpx.HTTPError:
            pass
    raise SystemExit("roll-out not finished after 20 minutes; check the ECS console")


if __name__ == "__main__":
    main()
