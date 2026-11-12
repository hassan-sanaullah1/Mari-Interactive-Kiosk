# The admin panel

The page at `/admin` on the frontend, where the knowledge-base files the kiosk
answers from are added, downloaded and deleted.

    http://<kiosk-host>:3000/admin

`http://<kiosk-host>:8010/upload`, the address the panel used to live at, redirects
here. The API behind the page is still served from the backend under `/upload/*`
(see `server/admin.py`); the browser reaches it as `/api/admin/*` through the Next
rewrite in `frontend/next.config.ts`.

## Signing in

One account, a username and a password. There is no sign-up and no second user.

The first sign-in on a fresh deployment uses:

| | |
|---|---|
| Username | `mari` |
| Password | whatever `MARI_ADMIN_TOKEN` is set to in `.env` |

**With `MARI_ADMIN_TOKEN` empty every admin route returns 503.** No token
configured means the panel is closed, not open.

The session lives in the browser's `sessionStorage`, so it is per-browser and ends
when the tab closes. Signing in on one machine gives no access on another, and every
request is checked by the server regardless of what the browser believes.

## Changing the username and password

**Change password** in the panel's top bar. It asks for the current password as well
as the new details, so a browser left signed in on the kiosk cannot be used to lock
the owner out.

The new pair is written to `admin-credentials.json` on the `rag_state` volume, at
`/app/state/` inside the backend container. The password is stored as an scrypt hash
with a random salt — it is not recoverable from the file, by anyone.

Once that file exists, `MARI_ADMIN_TOKEN` **stops being accepted**. That is the point
of changing the password: the old one has to stop working, or nothing was retired.

## Forgotten username or password

The password cannot be read back — it is hashed. Recovery means resetting the stored
credentials, which needs SSH access to the kiosk. That is deliberate: SSH is the
existing trust boundary, so anyone who can reset the panel can already reach the files
it manages.

    ssh mari@<kiosk-host>
    docker exec mari-interactive-kiosk-backend-1 \
        rm -f /app/state/admin-credentials.json

Nothing else is affected: no restart, no rebuild, and the knowledge base is untouched.
The panel immediately goes back to:

| | |
|---|---|
| Username | `mari` |
| Password | the `MARI_ADMIN_TOKEN` in `.env` |

Sign in with those and set a new pair through **Change password**.

If `.env` has also been lost, set a token and restart the backend so it is picked up:

    cd ~/Desktop/Mari-Interactive-Kiosk
    echo 'MARI_ADMIN_TOKEN=<a-new-password>' >> .env
    docker compose up -d backend

### Reading the username without signing in

The username is stored in clear; only the password is hashed. To check which account
name is current:

    docker exec mari-interactive-kiosk-backend-1 \
        python -c "import json;print(json.load(open('/app/state/admin-credentials.json'))['user'])"

If that is enough to get back in, no reset is needed.

## What survives what

| Event | Credentials survive? |
|---|---|
| Container restart or recreate | yes |
| `docker compose build` + redeploy | yes |
| Deleting the `rag_state` volume | **no** — back to `mari` + `MARI_ADMIN_TOKEN` |
| Deleting `admin-credentials.json` | **no** — this is the reset above |

The volume also holds the retrieval metadata database, so deleting it to reset a
password would also force a full re-ingest of the corpus. Delete the one file, not
the volume.
