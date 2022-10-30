# MapDiffBot-DMM

MapDiffBot-DMM generates DMM files showing the changes in a map via GitHub's Checks API, in a convenient format with easily locatable changes.

Features integration with [FastDMM2](https://fastdmm2.ss13.io/) for easy in-browser full diff viewing.

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

`fastdmm-host`: Host for FastDMM links, in case you want to use a fork.

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

Create a client secret, save it to the server's filesystem, and set `app-key` to the path to the file.

Copy the App ID and put it into `app-id`.

Optionally, create a webhook secret, put it into `webhook-secret`.

## Deployment

There are many options for deploying Flask applications, pick any from [Flask's deployment guide](https://flask.palletsprojects.com/en/1.1.x/deploying/#deployment).

Do note that due to how this is written, it won't work without an accessible local filesystem. Depending on your deployment, you may want to disable `host-dmms`, as many webservers can easily serve a folder as downloads with little configuration.

For use with `mod_wsgi`, a `mapdiffbot-dmm.wsgi` is included.

Also note that python is picky about module folder names, you should rename the folder of the downloaded copy of this repo to `mapdiffbotdmm`.

### Example Deployment (Debian+Apache2)

```sh
# Install python and wsgi
sudo apt install python3 python3-pip libapache2-mod-wsgi-py3
# Enable wsgi for apache2
sudo a2enmod wsgi
# Create system user and /srv/mdb directory
sudo useradd -m -r -d /srv/mdb -s /usr/sbin/nologin wsgi-mdb
sudo git clone https://github.com/itsmeow/MapDiffBot-DMM -C /srv/mdb/mapdiffbotdmm
# Install required packages
sudo pip install -r /srv/mdb/mapdiffbotdmm/requirements.txt
# Set directory permissions and ownership
sudo chmod 750 /srv/mdb
sudo chown wsgi-mdb:wsgi-mdb /srv/mdb
sudo mkdir /var/www/dmms
sudo chmod 755 /var/www/dmms
sudo chown wsgi-mdb:wsgi-mdb /var/www/dmms
```

#### /etc/apache2/sites-available/mdb.conf

This assumes you already have a working SSL configuration, otherwise, just use HTTP and change the virtual host to \*:80

##### File contents

```xml
<VirtualHost *:80>
        ServerName example.com
        RewriteEngine On
        RewriteCond %{HTTPS} !=on
        RewriteRule ^/?(.*) https://%{SERVER_NAME}/$1 [R,L]
</VirtualHost>
<VirtualHost *:443>
        ServerName example.com
        WSGIDaemonProcess MapDiffBot-DMM user=wsgi-mdb group=wsgi-mdb threads=5
        WSGIScriptAlias / /srv/mdb/mapdiffbot-dmm.wsgi
        AddHandler default-handler dmm
        <FilesMatch "\.dmm$">
                Header set Content-Disposition attachment
        </FilesMatch>
        <Location /*>
                Require all denied
        </Location>
        <Location /map-diff>
                Require all granted
                Header set Access-Control-Allow-Origin "*"
        </Location>
        <Location /webhook>
                Require all granted
        </Location>
        <Directory /srv/mdb>
                WSGIProcessGroup MapDiffBot-DMM
                WSGIApplicationGroup %{GLOBAL}
                Require all granted
        </Directory>
        Alias /map-diff/ /var/www/dmms/
        <Directory /var/www/dmms>
                Header set Access-Control-Allow-Origin "*"
                Require all granted
        </Directory>
        ErrorLog ${APACHE_LOG_DIR}/mdb_error.log
        LogLevel info
        CustomLog ${APACHE_LOG_DIR}/mdb_access.log combined
</VirtualHost>
```

##### Run after creating config

```sh
sudo a2ensite mdb
```

##### Once done with deployment

```
sudo systemctl restart apache2
```

##### Check for errors

```
sudo tail /var/log/apache2/error.log
sudo tail /var/log/apache2/mdb_error.log
```

#### /srv/mdb

##### Directory Permissions

```
sudo chmod 750 /srv/mdb
sudo chown wsgi-mdb:wsgi-mdb /srv/mdb
```

```
rwxr-x--- wsgi-mdb wsgi-mdb
```

##### /srv/mdb/priv_key.pem

```
-----BEGIN RSA PRIVATE KEY-----
Your GH application privkey here
-----END RSA PRIVATE KEY-----
```

##### /srv/mdb/mapdiffbot-dmm.wsgi

```python
#!/usr/bin/python
import sys
import logging
logging.basicConfig(stream=sys.stdout)
sys.path.insert(0, "/srv/mdb")
from mapdiffbotdmm.server import app as application
```

##### /srv/mdb/mapdiffbotdmm/config.json

```
{
  "name": "MapDiffBot-DMM",
  "app-id": "Your GH application ID here",
  "app-key-path": "/srv/mdb/priv_key.pem",
  "host": "https://example.com",
  "dmm-url": "/map-diff",
  "webhook-path": "/webhook",
  "webhook-secret": "Your GH application webhook secret here",
  "fastdmm-host": "https://fastdmm2.ss13.io",
  "dmm-save-path": "/var/www/dmms/",
  "host-dmms": false,
  "banned-repos": [],
  "threads-network": 7,
  "threads-fileio": 20,
  "debug": false,
  "threaded": true,
  "port": 5000
}
```

#### /var/www/dmms

##### Directory Permissions

```
sudo chmod 755 /var/www/dmms
sudo chown wsgi-mdb:wsgi-mdb /var/www/dmms
```

```
rwxr-xr-x wsgi-mdb wsgi-mdb
```
