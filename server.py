import asyncio
import os
import sys
import re
import json
import hmac
import hashlib
import requests
import concurrent
from datetime import datetime
from .dmm import _parse
from .diff import create_diff
from flask import Flask, request, send_from_directory
from github import Github, GithubIntegration

import pathlib
config_path = pathlib.Path(__file__).parent.resolve()

# Parse config
# --------------

config = {}

try:
    f = open(os.path.join(config_path, "config.json"))
    config = json.load(f)
    f.close()
except Exception as e:
    print(e)
    print("Error reading config!", file=sys.stderr)
    exit(1)

name = config["name"]
if not name or len(name) == 0:
    print("Must specify a check name in config!", file=sys.stderr)
    exit(1)
port = config["port"]
if not port in range(0, 65536):
    print("Port must be a number between 0 and 65536 in config!", file=sys.stderr)
    exit(1)
host = config["host"]
if host.endswith("/"):
    host[:len(host) - 1]
if not host or len(host) == 0:
    print("Must specify a host url in config!", file=sys.stderr)
    exit(1)
dmm_url = config["dmm-url"]
if not dmm_url.startswith("/"):
    print("DMM url must start with a slash!", file=sys.stderr)
    exit(1)
if dmm_url.endswith("/"):
    dmm_url[:len(dmm_url) - 1]
if not dmm_url or len(dmm_url) == 0:
    print("Must specify a dmm url in config!", file=sys.stderr)
    exit(1)
dmm_save_path = config["dmm-save-path"]
if not dmm_save_path.endswith("/"):
    dmm_save_path += "/"
if not dmm_save_path or len(dmm_save_path) == 0:
    print("Must specify a DMM save path in config!", file=sys.stderr)
    exit(1)
if not os.path.exists(dmm_save_path):
    os.makedirs(dmm_save_path)
    print("Creating DMM save folder...")
if not os.access(dmm_save_path, os.W_OK):
    print(f"Cannot write to specified DMM save path: {dmm_save_path}", file=sys.stderr)
    exit(1)
webhook_path = config["webhook-path"]
if not webhook_path.startswith("/"):
    print("Webhook path must start with a slash!", file=sys.stderr)
    exit(1)
if webhook_path.endswith("/"):
    webhook_path[:len(webhook_path) - 1]
if not webhook_path or len(webhook_path) == 0:
    print("Must specify a webhook path in config!", file=sys.stderr)
    exit(1)
fastdmm_host = config["fastdmm-host"]
if fastdmm_host.endswith("/"):
    fastdmm_host[:len(fastdmm_host) - 1]

# App
# -----------

app_key = None

try:
    with open(config["app-key-path"]) as key:
        app_key = key.read()
except Exception as e:
    print(e)
    print("Error reading app key!", file=sys.stderr)
    exit(1)

app = Flask(__name__)
git = GithubIntegration(
    config["app-id"],
    app_key,
)

@app.route(webhook_path, methods=["POST"])
async def hook_receive():
    if len(config["webhook-secret"]):
        if not validate_signature(request, config["webhook-secret"]):
            return "invalid signature", 400
    data = request.json
    if not "action" in data.keys() or not "pull_request" in data.keys() or not data["action"] in ["opened", "synchronize"]:
        print(f"Invalid action or schema: {data['action']} {data.keys()}", file=sys.stderr)
        return "invalid action/schema", 400

    owner = data["repository"]["owner"]["login"]
    repo_name = data["repository"]["name"]
    full_name = data["repository"]["full_name"]
    if not owner or not repo_name:
        print(f"Missing owner/repo_name: {owner}/{repo_name}", file=sys.stderr)
        return "missing owner/repo", 400
    if full_name in config["banned-repos"]:
        print(f"Request from banned repository: {full_name}", file=sys.stderr)
        return "banned repository", 403
    if owner in config["banned-users"]:
        print(f"Request from banned user: {full_name}", file=sys.stderr)
        return "banned user", 403

    asyncio.get_running_loop().create_task(do_request(data, owner, repo_name, full_name))
    return "ok"

async def do_request(data, owner, repo_name, full_name):
    token = git.get_access_token(
        git.get_installation(owner, repo_name).id
    ).token
    git_connection = Github(
        login_or_token=token
    )

    pull_request = data["pull_request"]
    commit_head_sha = pull_request["head"]["sha"]
    before = pull_request["base"]["sha"]
    after = commit_head_sha
    unique_id = re.sub(r'[^\w]', '-', full_name + "-" + str(pull_request["id"]) + "-" + before + "-" + after)

    repo = git_connection.get_repo(full_name)

    if "[mdb ignore]" in pull_request["title"].lower() and not "[mdb ignore]dmm" in pull_request["title"].lower():
        repo.create_check_run(
        name=name,
        head_sha=commit_head_sha,
        started_at=get_iso_time(),
        completed_at=get_iso_time(),
        conclusion="skipped",
        output={
            "title": "Ignored",
            "summary": "pull request ignored due to [MDB IGNORE] in title. Use [MDB IGNORE]DMM to allow MDB-DMM, but not other MDBs."
        })
        return

    check_run_object = repo.create_check_run(
    name=name,
    head_sha=commit_head_sha,
    status="in_progress",
    started_at=get_iso_time())

    diff = repo.compare(before, after)
    maps_changed = list(filter(lambda file: file.status == "modified" and file.filename.endswith(".dmm"), diff.files))
    print(f"Created check run {unique_id} ({len(maps_changed)} maps changed)", file=sys.stderr)

    result_text = "## Maps Changed\n\n" if len(maps_changed) > 0 else "No maps changed"


    downloads = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=config["threads-network"]) as executor:
        download_tasks = []
        for file in maps_changed:
            b = executor.submit(get_fileset, full_name, file.filename, before, after, token)
            download_tasks.append(b)
        print(f"Downloading {unique_id}", file=sys.stderr)
        for future in concurrent.futures.as_completed(download_tasks):
            try:
                downloads.append(future.result())
            except Exception as e:
                print(e)
                print(f"WARNING: Encountered error for check {unique_id} while performing data download", file=sys.stderr)
                check_run_object.edit(
                completed_at=get_iso_time(),
                conclusion="skipped",
                output={
                    "title": "Internal error",
                    "summary": "error encountered while performing data download"
                }
                )
                return
    result_entries = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=config["threads-fileio"]) as executor:
        print(f"Parsing {unique_id}", file=sys.stderr)
        diff_tasks = []
        for download in downloads:
            before_text, after_text, filename = download
            before_dmm = _parse(before_text)
            after_dmm = _parse(after_text)
            d = executor.submit(create_diff, before_dmm, after_dmm, filename)
            diff_tasks.append(d)
        diffs = []
        try:
            print(f"Diffing {unique_id}", file=sys.stderr)
            for future in concurrent.futures.as_completed(diff_tasks):
                diffs.append(future.result())
        except Exception as e:
            print(e)
            print(f"WARNING: Encountered error for check {unique_id} while performing diff", file=sys.stderr)
            check_run_object.edit(
            completed_at=get_iso_time(),
            conclusion="skipped",
            output={
                "title": "Internal error",
                "summary": "error encountered while performing diff"
            }
            )
            return
        io_tasks = []
        for diff in diffs:
            tiles_changed, diff_dmm, note, movables_added, movables_deleted, turfs_changed, areas_changed, filename = diff
            result_entry = f"### {filename}\n\n"
            if not note is None:
                result_entry += f"{note}\n\n"
            if(diff_dmm == None):
                continue
            # Get around GitHub's character limit
            if len(maps_changed) <= 100:
                result_entry += f"{tiles_changed} tiles changed\n"
                result_entry += f"{movables_added} movables added, {movables_deleted} movables deleted\n"
                result_entry += f"{turfs_changed} turfs changed\n"
                result_entry += f"{areas_changed} areas changed\n"
            file_uuid = unique_id + "-" + re.sub(r'[^\w]', '-', filename)
            # Generate a unique name hashed on all unique fields
            file_name_safe = hashlib.sha1(file_uuid.encode("utf-8")).hexdigest() + ".dmm"
            out_file_path = dmm_save_path + file_name_safe
            full_url = f"{host}{dmm_url}/{file_name_safe}"
            result_entry += f"Download: [diff]({full_url})\n"
            if fastdmm_host and len(fastdmm_host) > 0:
                result_entry += f"FastDMM: "
                if len(maps_changed) <= 50:
                    result_entry += f"[base repo]({fastdmm_host}?repo={full_name}&branch={before}&map={full_url}) - "
                result_entry += f"[head repo]({fastdmm_host}?repo={full_name}&branch={after}&map={full_url})\n"
            t = executor.submit(diff_dmm.to_file, out_file_path, do_gzip=config["use-gzip"])
            io_tasks.append(t)
            #print(f"Generated diff: {out_file_path}", file=sys.stderr)
            result_entries.append((result_entry, tiles_changed))
        try:
            print(f"Starting writes", file=sys.stderr)
            for future in concurrent.futures.as_completed(io_tasks):
                future.result()
            print(f"Writes complete", file=sys.stderr)
        except Exception as e:
            print(e)
            print(f"WARNING: Encountered error for check {unique_id} while writing", file=sys.stderr)
            check_run_object.edit(
            completed_at=get_iso_time(),
            conclusion="skipped",
            output={
                "title": "Internal error",
                "summary": "error encountered while writing"
            }
            )
            return

    # Sort by tiles changed
    for result_entry in sorted(result_entries, key=lambda entry: entry[1], reverse=True):
        result_text += result_entry[0]

    try:
        check_run_object.edit(
        completed_at=get_iso_time(),
        conclusion="success" if len(maps_changed) > 0 else "skipped",
        output={
            "title": f"{len(maps_changed)} map{'s' if len(maps_changed) != 1 else ''} changed" if len(maps_changed) > 0 else "No maps changed",
            "summary": "",
            "text": result_text,
        }
        )
    except Exception as e:
        print(e)
        print(f"WARNING: Error while editing check run {unique_id}", file=sys.stderr)
        check_run_object.edit(
        completed_at=get_iso_time(),
        conclusion="skipped",
        output={
            "title": "Internal error",
            "summary": "error encountered while updating check run status. The diff may be too large.",
        }
        )


@app.route(dmm_url + "/<filename>", methods=["GET"])
def get_dmm(filename):
    if not config["host-dmms"]:
        return "DMM hosting disabled, if you're seeing this, the server is probably misconfigured."
    elif config["use-gzip"]:
        print(f"WARNING: Server is configured to use gzip, but the builtin DMM fileserver does not support it! Disable use-gzip or use an external webserver.", file=sys.stderr)
    return send_from_directory(directory=dmm_save_path, path=filename, as_attachment=True)

# Helpers
# --------

def get_file(url, token):
    return requests.get(url, headers={"Accept": "application/vnd.github.3.raw", "Authorization": f"Bearer {token}"}).text

def get_fileset(full_name, filename, before, after, token):
    before =  get_file(f"https://api.github.com/repos/{full_name}/contents/{filename}?ref={before}", token)
    after = get_file(f"https://api.github.com/repos/{full_name}/contents/{filename}?ref={after}", token)
    return (before, after, filename)

def get_iso_time():
    return datetime.utcnow().replace(microsecond=0)

def validate_signature(payload, secret):
    if not 'X-Hub-Signature' in payload.headers:
        print(f"No signature detected, ignoring request", file=sys.stderr)
        return False
    signature_header = payload.headers['X-Hub-Signature']
    sha_name, github_signature = signature_header.split('=')
    if sha_name != 'sha1':
        print('ERROR: X-Hub-Signature in payload headers was not sha1=****', file=sys.stderr)
        return False
    local_signature = hmac.new(secret.encode('utf-8'), msg=payload.data, digestmod=hashlib.sha1)
    return hmac.compare_digest(local_signature.hexdigest(), github_signature)

# Testing
# ----------

if __name__ == "__main__":
    app.run(debug=config["debug"], port=config["port"], threaded=config["threaded"])