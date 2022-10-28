import os
import sys
import re
import json
import hmac
import hashlib
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
except:
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

# App
# -----------

app_key = None

try:
    with open(config["app-key-path"]) as key:
        app_key = key.read()
except:
    print("Error reading app key!", file=sys.stderr)
    exit(1)

app = Flask(__name__)
git = GithubIntegration(
    config["app-id"],
    app_key,
)

@app.route(webhook_path, methods=["POST"])
def hook_receive():
    if len(config["webhook-secret"]):
        if not validate_signature(request, config["webhook-secret"]):
            return "invalid signature"
    data = request.json
    if not "action" in data.keys() or not "pull_request" in data.keys() or not data["action"] in ["opened", "synchronize"]:
        print(f"Invalid action or schema: {data['action']} {data.keys()}", file=sys.stderr)
        return "ok"

    owner = data["repository"]["owner"]["login"]
    repo_name = data["repository"]["name"]
    full_name = data["repository"]["full_name"]
    if not owner or not repo_name:
        print(f"Missing owner/repo_name: {owner}/{repo_name}", file=sys.stderr)
        return "ok"
    if full_name in config["banned-repos"]:
        print(f"Request from banned repository: {full_name}", file=sys.stderr)
        return "ok"
    git_connection = Github(
        login_or_token=git.get_access_token(
            git.get_installation(owner, repo_name).id
        ).token
    )

    pull_request = data["pull_request"]
    commit_head_sha = pull_request["head"]["sha"]
    before = pull_request["base"]["sha"]
    after = commit_head_sha
    unique_id = re.sub(r'[^\w]', '-', full_name + "-" + str(pull_request["id"]) + "-" + before + "-" + after)

    repo = git_connection.get_repo(full_name)

    if "[mdb ignore]" in pull_request["title"].lower():
        repo.create_check_run(
        name=name,
        head_sha=commit_head_sha,
        started_at=get_iso_time(),
        completed_at=get_iso_time(),
        conclusion="skipped",
        output={
            "title": name,
            "summary": "pull request ignored"
        })
        return "ok"

    check_run_object = repo.create_check_run(
    name=name,
    head_sha=commit_head_sha,
    status="in_progress",
    started_at=get_iso_time())

    diff = repo.compare(before, after)
    maps_changed = list(filter(lambda file: file.status == "modified" and file.filename.endswith(".dmm"), diff.files))
    print(f"Created check run {unique_id} ({maps_changed} maps changed)", file=sys.stderr)

    result_text = "## Maps Changed\n\n" if len(maps_changed) > 0 else "No maps changed"

    for file in maps_changed:
        before_data = None
        after_data = None
        before_dmm = None
        after_dmm = None
        try:
            before_data = repo.get_contents(file.filename, ref=before).decoded_content.decode("utf-8")
            after_data = repo.get_contents(file.filename, ref=after).decoded_content.decode("utf-8")
            before_dmm = _parse(before_data)
            after_dmm = _parse(after_data)
        except:
            print(f"Skipping map file {file.filename} due to error parsing data")
            result_text += f"### {file.filename}\n\n"
            result_text += f"Skipped due to error parsing data"
            continue
        try:
            tiles_changed, diff_dmm, note, movables_added, movables_deleted, turfs_changed, areas_changed = create_diff(before_dmm, after_dmm)
            result_text += f"### {file.filename}\n\n"
            if not note is None:
                result_text += f"{note}\n\n"
            if(diff_dmm == None):
                continue
            result_text += f"{tiles_changed} tiles changed\n"
            result_text += f"{movables_added} movables added, {movables_deleted} movables deleted\n"
            result_text += f"{turfs_changed} turfs changed\n"
            result_text += f"{areas_changed} areas changed\n"
            file_name_safe = unique_id + ".dmm"
            out_file_path = dmm_save_path + file_name_safe
            result_text += f"Download: [diff]({host}{dmm_url}/{file_name_safe})\n"
            try:
                diff_dmm.to_file(out_file_path)
                print(f"Writing diff: {out_file_path}", file=sys.stderr)
            except:
                print(f"WARNING: Encountered error for check {unique_id} while writing to file: {out_file_path}", file=sys.stderr)
                check_run_object.edit(
                completed_at=get_iso_time(),
                conclusion="failure",
                output={
                    "title": name,
                    "summary": f"error encountered while writing file"
                }
                )
                return "ok"
        except:
            print(f"WARNING: Encountered error for check {unique_id} while performing diff", file=sys.stderr)
            check_run_object.edit(
            completed_at=get_iso_time(),
            conclusion="failure",
            output={
                "title": name,
                "summary": f"error encountered while performing diff"
            }
            )
            return "ok"

    check_run_object.edit(
    completed_at=get_iso_time(),
    conclusion="success" if len(maps_changed) > 0 else "skipped",
    output={
        "title": name,
        "summary": f"{len(maps_changed)} maps changed",
        "text": result_text,
    }
    )

    return "ok"


@app.route(dmm_url + "/<filename>", methods=["GET"])
def get_dmm(filename):
    if not config["host-dmms"]:
        return "DMM hosting disabled, if you're seeing this, the server is probably misconfigured."
    return send_from_directory(directory=dmm_save_path, path=filename, as_attachment=True)

# Helpers
# --------

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