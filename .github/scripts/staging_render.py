"""Inspect staging only; use --deploy for the exact develop commit."""
import os
import re
import sys
import time
from urllib.parse import urlencode

from render_release import RENDER_API, request_json, trigger_deploy, wait_for_deploy

NAME = 'daily-trivia-backend-staging'
URL = 'https://daily-trivia-backend-staging.onrender.com'


def validate(service, production_id):
    if (service.get('name') != NAME or service.get('id') == production_id or
            service.get('type') != 'web_service' or
            service.get('serviceDetails', {}).get('url') != URL or
            service.get('branch') != 'develop' or
            service.get('repo', '').rstrip('/') not in
            {'https://github.com/boiniku/daily-trivia', 'https://github.com/boiniku/daily-trivia.git'}):
        raise ValueError('Refusing a service that does not match staging, develop and this repository')


def inspect_logs(service, token):
    query = urlencode(dict(ownerId=service['ownerId'], resource=service['id'], limit=100,
                           direction='backward'))
    payload = request_json(f'{RENDER_API}/logs?{query}', token=token)
    for line in reversed(payload.get('logs', [])):
        message = line.get('message', '')
        if re.search(r'Error|Exception|File ".*\.py"|failed|exited|Traceback', message):
            message = re.sub(r'(?:postgres(?:ql)?(?:\+psycopg2)?|https?)://\S+', '[URL]', message)
            message = re.sub(r'(?i)(password|token|secret|key)\s*[=:]\s*\S+', r'\1=[REDACTED]', message)
            print(message[:1000], flush=True)


def main():
    if os.environ.get('GITHUB_REF') != 'refs/heads/develop':
        raise ValueError('Only develop may operate on staging')
    token = os.environ['RENDER_API_KEY']
    production_id = os.environ['PRODUCTION_SERVICE_ID']
    query = urlencode(dict(name=NAME, limit=100))
    rows = request_json(f'{RENDER_API}/services?{query}', token=token)
    matches = [row['service'] for row in rows if row['service'].get('name') == NAME]
    if len(matches) != 1:
        raise ValueError('Expected exactly one staging service')
    service = matches[0]
    validate(service, production_id)
    print('Staging verified:', {key: service.get(key) for key in ('name', 'branch', 'rootDir', 'autoDeploy')}, flush=True)
    deployments = request_json(f"{RENDER_API}/services/{service['id']}/deploys?limit=3", token=token)
    print('Recent staging deploys:', [dict(status=row['deploy']['status'],
          commit=row['deploy'].get('commit', {}).get('id')) for row in deployments], flush=True)
    inspect_logs(service, token)
    if '--deploy' not in sys.argv:
        return
    commit = os.environ['GITHUB_SHA']
    deploy_id = trigger_deploy(service['id'], token, {'commitId': commit})
    try:
        wait_for_deploy(service['id'], deploy_id, token, timeout_seconds=900)
    except Exception:
        inspect_logs(service, token)
        raise
    for _ in range(24):
        health = request_json(URL + '/health')
        if health.get('environment') == 'staging' and health.get('release_commit') == commit:
            print('Staging release verified:', commit, flush=True)
            return
        time.sleep(10)
    raise TimeoutError('Staging did not report the requested commit')


if __name__ == '__main__':
    main()
