#!/usr/bin/env python3
"""Small, dependency-free Render release helper used by GitHub Actions."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


RENDER_API = "https://api.render.com/v1"
FAILED_STATUSES = {"build_failed", "update_failed", "canceled", "deactivated"}
EXPECTED_ROOT_DIR = "apps/api"
EXPECTED_BUILD_COMMAND = "pip install -r requirements.txt"
EXPECTED_START_COMMAND = (
    "python -m scripts.migrations.migrate_trivia_candidates "
    "&& uvicorn main:app --host 0.0.0.0 --port $PORT"
)


def request_json(url: str, *, token: str | None = None, method: str = "GET", body=None):
    headers = {"Accept": "application/json", "User-Agent": "daily-trivia-release/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed ({error.code}): {detail}") from error


def trigger_deploy(service_id: str, token: str, body: dict) -> str:
    deploy = request_json(
        f"{RENDER_API}/services/{urllib.parse.quote(service_id)}/deploys",
        token=token,
        method="POST",
        body=body,
    )
    deploy_id = deploy.get("id")
    if not deploy_id:
        raise RuntimeError(f"Render did not return a deploy id: {deploy}")
    print(f"Triggered Render deploy {deploy_id}", flush=True)
    return str(deploy_id)


def configure_production_service(service_id: str, token: str):
    """Migrate the existing service from the old backend/ layout safely."""
    service_url = f"{RENDER_API}/services/{urllib.parse.quote(service_id)}"
    current = request_json(service_url, token=token)
    if current.get("type") != "web_service":
        raise RuntimeError(f"Expected a Render web service, got: {current.get('type')}")

    print(
        "Current Render configuration: "
        f"branch={current.get('branch')} rootDir={current.get('rootDir')}",
        flush=True,
    )
    request_json(
        service_url,
        token=token,
        method="PATCH",
        body={
            "autoDeploy": "no",
            "branch": "main",
            "rootDir": EXPECTED_ROOT_DIR,
            "serviceDetails": {
                "runtime": "python",
                "healthCheckPath": "/health",
                "envSpecificDetails": {
                    "buildCommand": EXPECTED_BUILD_COMMAND,
                    "startCommand": EXPECTED_START_COMMAND,
                },
            },
        },
    )
    configured = request_json(service_url, token=token)
    details = configured.get("serviceDetails") or {}
    native = details.get("envSpecificDetails") or {}
    actual = {
        "branch": configured.get("branch"),
        "rootDir": configured.get("rootDir"),
        "healthCheckPath": details.get("healthCheckPath"),
        "buildCommand": native.get("buildCommand"),
        "startCommand": native.get("startCommand"),
    }
    expected = {
        "branch": "main",
        "rootDir": EXPECTED_ROOT_DIR,
        "healthCheckPath": "/health",
        "buildCommand": EXPECTED_BUILD_COMMAND,
        "startCommand": EXPECTED_START_COMMAND,
    }
    if actual != expected:
        raise RuntimeError(f"Render configuration verification failed: {actual}")
    print(f"Render configuration verified: {actual}", flush=True)


def wait_for_deploy(service_id: str, deploy_id: str, token: str, timeout_seconds: int = 1800):
    deadline = time.monotonic() + timeout_seconds
    last_status = None
    while time.monotonic() < deadline:
        deploy = request_json(
            f"{RENDER_API}/services/{urllib.parse.quote(service_id)}/deploys/{urllib.parse.quote(deploy_id)}",
            token=token,
        )
        status = str(deploy.get("status", "unknown"))
        if status != last_status:
            print(f"Render deploy status: {status}", flush=True)
            last_status = status
        if status == "live":
            return
        if status in FAILED_STATUSES or status.endswith("_failed"):
            raise RuntimeError(f"Render deploy ended with status {status}")
        time.sleep(15)
    raise TimeoutError(f"Render deploy {deploy_id} did not become live within {timeout_seconds}s")


def wait_for_health(health_url: str, expected_commit: str, timeout_seconds: int = 300):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            health = request_json(health_url)
            deployed_commit = str(health.get("release_commit", ""))
            if (
                health.get("status") == "ok"
                and health.get("environment") == "production"
                and deployed_commit == expected_commit
            ):
                print(f"Production health verified at commit {deployed_commit}", flush=True)
                return
            print(f"Waiting for exact production commit; health={health}", flush=True)
        except Exception as error:  # The old instance may briefly be unavailable.
            print(f"Health check retry: {error}", flush=True)
        time.sleep(10)
    raise TimeoutError(f"Production did not report commit {expected_commit}")


def public_app_store_version(app_store_id: str, country: str = "jp") -> str:
    query = urllib.parse.urlencode({"id": app_store_id, "country": country})
    payload = request_json(f"https://itunes.apple.com/lookup?{query}")
    results = payload.get("results") or []
    if not results:
        raise RuntimeError(f"App Store lookup returned no app for id {app_store_id}")
    return str(results[0].get("version", "")).strip()


def deploy(args):
    configure_production_service(args.service_id, args.token)
    deploy_id = trigger_deploy(args.service_id, args.token, {"commitId": args.commit})
    wait_for_deploy(args.service_id, deploy_id, args.token)
    wait_for_health(args.health_url, args.commit)


def activate_update_prompt(args):
    published_version = public_app_store_version(args.app_store_id)
    if published_version != args.version:
        raise RuntimeError(
            f"Refusing to enable the prompt: App Store publishes {published_version!r}, "
            f"not {args.version!r}"
        )
    print(f"App Store publication verified: {published_version}", flush=True)

    key = urllib.parse.quote("LATEST_APP_VERSION")
    request_json(
        f"{RENDER_API}/services/{urllib.parse.quote(args.service_id)}/env-vars/{key}",
        token=args.token,
        method="PUT",
        body={"value": args.version},
    )
    deploy_id = trigger_deploy(args.service_id, args.token, {"deployMode": "deploy_only"})
    wait_for_deploy(args.service_id, deploy_id, args.token)

    version_url = args.health_url.rsplit("/health", 1)[0] + "/app/version"
    payload = request_json(version_url)
    if payload.get("latest_version") != args.version:
        raise RuntimeError(f"Update prompt verification failed: {payload}")
    print(f"Update prompt enabled for {args.version}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy_parser = subparsers.add_parser("deploy")
    deploy_parser.add_argument("--service-id", required=True)
    deploy_parser.add_argument("--token", required=True)
    deploy_parser.add_argument("--commit", required=True)
    deploy_parser.add_argument("--health-url", required=True)
    deploy_parser.set_defaults(handler=deploy)

    prompt_parser = subparsers.add_parser("activate-update-prompt")
    prompt_parser.add_argument("--service-id", required=True)
    prompt_parser.add_argument("--token", required=True)
    prompt_parser.add_argument("--version", required=True)
    prompt_parser.add_argument("--health-url", required=True)
    prompt_parser.add_argument("--app-store-id", required=True)
    prompt_parser.set_defaults(handler=activate_update_prompt)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"release error: {error}", file=sys.stderr)
        raise SystemExit(1)
