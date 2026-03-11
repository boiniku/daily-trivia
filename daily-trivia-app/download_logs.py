import json
import urllib.request
import re

def find_logs_url(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == 'logsUrl' and isinstance(v, str) and v.startswith('http'):
                return v
            res = find_logs_url(v)
            if res: return res
    elif isinstance(obj, list):
        for item in obj:
            res = find_logs_url(item)
            if res: return res
    return None

try:
    with open('build_info.json', 'r', encoding='utf-8') as f:
        content = f.read()
    
    json_start = content.find('{')
    if json_start != -1:
        data = json.loads(content[json_start:])
        url = find_logs_url(data)
        if url:
            print("Found URL:", url)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                logs = response.read().decode('utf-8')
            
            with open('raw_build_logs.txt', 'w', encoding='utf-8') as f:
                f.write(logs)
            print("Downloaded logs successfully.")
        else:
            print("No logsUrl found in JSON.")
except Exception as e:
    print("Error:", e)
