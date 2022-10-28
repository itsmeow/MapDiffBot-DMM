# MapDiffBot-DMM

MapDiffBot-DMM generates DMM files showing the changes in a map via GitHub's Checks API, in a convenient format with easily locatable changes.

## Diffs

![MDB-DMM diff New marker - new contents - Old marker - old contents - End marker - TURF DIFF: old TO new - AREA DIFF: old TO new - new turf - new area](https://i.imgur.com/YBW6iq9.png)

Diffs can be generated directly (without using GitHub) by directly calling diff.py with files as arguments.

Example (run from a directory above the repo, with the repo folder named MapDiffBot-DMM, because python is a terrible language for modular code):

```sh
python -m MapDiffBot-DMM.diff old.dmm new.dmm diff.dmm
```

## Configuration

`app-id`: The App ID of your Github app. Listed under "About"

`app-key-path`: This is the path to the file containing the private key for your app. Generate one and then put it in the repo folder.

`host`: Base URL to direct map downloads to (if `host-dmms` is enabled, it should point to this server).

`dmm-url`: URL path to direct map downloads to (appended to host, starts with /). Also used to listen for requests if `host-dmms` is enabled.

`webhook-url`: URL path to listen for webhook requests on (start with /)

`webhook-secret`: Optional, webhook secret used to sign/verify requests are from GitHub, if you created one

`host-dmms`: If this server should host the DMM files from the folder it saves to and serve them.

`dmm-save-path`: Filesystem location to save DMM files to.

`banned-repos`: List of repo paths that are not processed (format: "Owner/RepoName")

`threads-network`: Threads dedicated to downloading maps (needs to be limited due to GitHub API usage)

`threads-fileio`: Threads dedicated to performing diffs and writing files.

### Development Options

`port`: Port to listen to webhook requests on.

`debug`: Enables Flask's debug mode.

`threaded`: Enables Flask's threading - you definitely want this, as it allows multiple requests to be processed asynchronously.

## GitHub App Setup

Go to [GitHub App settings](https://github.com/settings/apps), create an app.

Add the following permissions:

- Checks: Read and write
- Contents: Read-only
- Pull requests: Read-only

Create a webhook redirecting to `webhook-url` on your server, with the following event subscriptions:

- Pull request

Create a client secret, add it to the configuration `app-key`.

Copy the App ID and put it into `app-id`.

Optionally, create a webhook secret, put it into `webhook-secret`.

## Deployment

There are many options for deploying Flask applications, pick any from [Flask's deployment guide](https://flask.palletsprojects.com/en/1.1.x/deploying/#deployment).

Do note that due to how this is written, it won't work without an accessible local filesystem. Depending on your deployment, you may want to disable `host-dmms`, as many webservers can easily serve a folder as downloads with little configuration.

For use with `mod_wsgi`, a `mapdiffbot-dmm.wsgi` is included.

Also note that python is picky about module folder names, you should rename the folder of the downloaded copy of this repo to `mapdiffbotdmm`.
