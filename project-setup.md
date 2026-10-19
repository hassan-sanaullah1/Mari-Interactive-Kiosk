# New Project Setup


## 1. Create the repository

- **Owner:** the company GitHub organisation. Never a personal account.
- **Name:** `<project>-<component>`, lowercase with hyphens.

  | Good | Bad | Why |
  |---|---|---|
  | `orderdesk-api` | `OrderDesk_Backend_New` | Mixed case, underscore, "new" |
  | `orderdesk-web` | `frontend` | No project name |
  | `orderdesk-infra` | `ali-test-repo` | Personal name, no meaning |

  Standard component suffixes: `-api`, `-web`, `-mobile`, `-ml`, `-infra`, `-docs`.
- **Visibility:** Private.
- **Description:** one sentence saying what it is. Add topics for the project and the main stack.
- **Access:** grant access to GitHub teams, not individuals. Tech lead: Maintain. Developers and QA: Write.

## 2. Set up the branches

1. Create `develop` and `staging` from `main`.
2. Set `develop` as the default branch (Settings → General → Default branch). New PRs then target it automatically.

How the branches are used is covered in the [Git Workflow](git-workflow.md).

## 3. Add the standard files

```
.
├── .github/
│   ├── workflows/pr-checks.yml   # checks that must pass before a PR merges (section 10)
│   └── pull_request_template.md
├── docs/                         # anything too long for the README
├── scripts/
│   └── entrypoint.sh             # first thing that runs inside the container (section 8)
├── src/                          # application code (or the framework's equivalent)
├── .coderabbit.yaml              # see the CodeRabbit standard
├── .dockerignore
├── .editorconfig                 # basic formatting rules every editor applies
├── .env.example                  # documentation only: every variable name, with dummy values
├── .gitignore                    # must list .env
├── .infisical.json               # links the folder to its Infisical project; safe to commit
├── .pre-commit-config.yaml       # checks that run on every commit (section 10)
├── AGENTS.md                     # coding conventions for this repo
├── Dockerfile                    # how the image is built
├── docker-compose.yml            # what runs; read by Coolify and by `make dev`
├── docker-compose.override.yml   # laptop-only settings, merged in automatically (section 8)
├── Makefile                      # shortcuts for developers: setup, dev, down, lint
└── README.md
```

**`.editorconfig`** tells every editor (VS Code, JetBrains, Vim) the same basic formatting rules for this repo: indentation, line endings, final newline. Editors apply it automatically, so two people on different editors do not produce whitespace-only changes in each other's diffs.

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2

[*.py]
indent_size = 4

[Makefile]
indent_style = tab
```

**`.github/pull_request_template.md`**

```markdown
## What and why
<!-- 1–3 sentences -->

## How QA can verify

## Checklist
- [ ] I reviewed my own diff; CodeRabbit comments are resolved or answered
- [ ] Behind a feature flag if incomplete or risky
- [ ] New variables added to Infisical (all environments) and to `.env.example`
- [ ] README updated if run, config or deploy steps changed
- [ ] No secrets, debug code or commented-out blocks
```

**`AGENTS.md`** holds the project's conventions in plain language. CodeRabbit and coding agents read it automatically, so it doubles as review criteria. Start from this sample and edit it to match the project:

```markdown
# AGENTS.md

Rules for anyone changing this repository: developers, reviewers and AI coding agents.

## Project
orderdesk-api is the REST API for the OrderDesk portal.
Stack: Python 3.12, FastAPI, PostgreSQL, Redis, Docker.

## Commands
- `make setup` once per clone: installs the commit hooks, logs in to Infisical
- `make dev`   start the project locally with values from Infisical
- `make down`  stop it
- `make lint`  run every check on every file; the same checks run on each commit

## Structure
- `src/api/`       route handlers only: no business logic, no direct database access
- `src/services/`  business logic
- `src/models/`    database models
- `src/core/`      config, logging, shared utilities

## Conventions
- Type hints on every function. Pydantic models for every request and response.
- Every endpoint validates input, checks authorisation, and returns errors as
  `{"error": {"code": "...", "message": "..."}}`.
- Read configuration only through `src/core/config.py`. No `os.getenv` elsewhere.
- Log through the shared logger and include the request ID. No `print`.
- New or unfinished features go behind a flag named `enable_<feature>`, default off.

## Do not
- Commit secrets, `.env` files or real customer data. Secrets live in Infisical.
- Put secrets or environment values in the Dockerfile or pass them at build time.
- Add a dependency without explaining why in the PR description.
- Change the response shape of an existing endpoint without a flag or a new version.

## Git
- Branch: `<type>/<short-description>`, cut from `develop`.
- PR title: `<type>(<scope>): <summary>`.
- Scopes in this repo: `orders`, `billing`, `auth`, `api`, `db`, `config`, `deploy`, `deps`.
```

## 4. Write the README

A new developer should be able to run the project from the README alone, in under 15 minutes. It must contain these sections:

````markdown
# orderdesk-api

REST API for OrderDesk, the order management portal for <client>. Handles
orders, inventory and invoicing. Consumed by `orderdesk-web`.

## Tech stack
Python 3.12, FastAPI, PostgreSQL 16, Redis, Docker.

## Run locally
Prerequisites: Docker, Make, Infisical CLI, pre-commit, access to the `orderdesk-api` Infisical project.

    make setup          # once per clone: commit hooks + Infisical login
    make dev            # starts the API on http://localhost:8000
    make down           # stops it

API docs: http://localhost:8000/docs

## Configuration
All configuration is environment variables stored in Infisical (project
`orderdesk-api`, environments `local`, `dev`, `staging`, `prod`). `.env.example` lists
every variable name.

## Environments
| Environment | Branch | URL |
|---|---|---|
| Dev | `develop` | https://dev.orderdesk.example.com |
| Staging | `staging` | https://staging.orderdesk.example.com |
| Production | `main` | https://orderdesk.example.com |

All three are deployed by Coolify when their branch changes.

## Feature flags
| Flag | Purpose | Owner |
|---|---|---|
| `enable_bulk_export` | CSV export of orders | @alikhan |

## Project structure
    src/api/        route handlers
    src/services/   business logic
    src/models/     database models
    src/core/       config, logging, shared utilities

## Contacts
Tech lead: @name · Standards: <link to engineering standards>
````

Keep it current. A PR that changes how the project is run, configured or deployed updates the README in the same PR.

## 5. Naming conventions

| Thing | Convention | Example |
|---|---|---|
| Repository | kebab-case | `orderdesk-api` |
| Folders | kebab-case; use the framework's convention where it requires one | `order-items/`, Python packages `order_items/` |
| Python files | snake_case | `invoice_service.py` |
| JS/TS modules | kebab-case | `invoice-service.ts` |
| React components | PascalCase | `InvoiceTable.tsx` |
| Environment variables | UPPER_SNAKE_CASE, same name in every environment | `DATABASE_URL` |
| Feature flags | `enable_<feature>` | `enable_bulk_export` |
| Infisical project and machine identity | Repo name; repo name plus `-coolify` | `orderdesk-api`, `orderdesk-api-coolify` |
| Branches, commits, tags | See the Git Workflow | |

No spaces, and no `new`, `final`, `temp`, `copy`, `v2` or personal names in any file or folder name. Keep the same top-level layout in every repo so people can move between projects.

## 6. Configure GitHub

**Settings → General → Pull Requests**

| Setting | Value |
|---|---|
| Allow squash merging | On, default message "Pull request title" |
| Allow merge commits | On |
| Allow rebase merging | Off |
| Always suggest updating pull request branches | On |
| Automatically delete head branches | **On** |

Auto-delete is what removes a work branch once its PR is merged. It would also try to delete `develop` after a promotion PR, which is why the rulesets below must be in place first.

**Settings → Rules → Rulesets.** Create two branch rulesets (private repos need the GitHub Team plan or higher):

| Rule | `develop` | `staging`, `main`, `release/**` |
|---|---|---|
| Restrict deletions | On | On |
| Block force pushes | On | On |
| Require a pull request before merging | On | On |
| Required approvals | 1 | 1 for `staging`; 2 for `main` (tech lead + QA lead) |
| Dismiss stale approvals when new commits are pushed | On | On |
| Require conversation resolution | On | On |
| Require status checks to pass | PR checks from section 10 | PR checks from section 10 |
| Allowed merge methods | Squash, Merge | Merge |
| Bypass list | Empty | Empty |

**Release branches and status checks.** The PR checks workflow runs for `develop`, `staging` and `main` only. A required check that never runs blocks every merge, so when the first `release/vX.Y` branch is cut, either add `release/**` to the workflow's branch list or move release branches into their own ruleset without the status-check rule.

**Secrets and environments.** Nothing is stored in GitHub secrets or GitHub Environments. Secrets live in Infisical (section 7), and the approval gate for Production is the ruleset on `main`.

## 7. Set up secrets in Infisical

### The four environments

Every project has the same four environments. Commands use the **slug**, not the display name. Confirm the slugs under Project Settings → Environments; if yours differ, use yours in every command below.

| Environment | Slug | Holds values for | Read by |
|---|---|---|---|
| Local | `local` | Running the project on a laptop | Developers, through the CLI |
| Develop | `dev` | The Dev deployment on Coolify | The project's machine identity |
| Staging | `staging` | The Staging deployment on Coolify | The project's machine identity |
| Production | `prod` | The Production deployment on Coolify | The project's machine identity |

`local` exists because a laptop needs different values from a server: `localhost` URLs, a local or shared development database, debug switches on.

### Once per project (tech lead)

1. Create an Infisical project with the same name as the repo, with the four environments above.
2. Add every variable to all four environments, with the same name in each. Add the names to `.env.example` with dummy values. To load an existing `.env` in one go: `infisical secrets set --file=./.env --env=local`. Also add `APP_ENV` to each environment, set to that environment's own slug (`local`, `dev`, `staging`, `prod`); it is the guard described below.
3. Create **one** machine identity for the project: in the project, Access Control → Machine Identities → Add Machine Identity → Create New. Name it `<repo>-coolify` and give it a read-only role. Creating it inside the project means it cannot read any other project.
4. On the identity, open Universal Auth, copy the **Client ID**, select Create Client Secret and copy the **Client Secret**. It is shown once. These two values are the only secrets that ever leave Infisical; the same pair goes into all three Coolify applications in section 9.
5. Copy the **Project ID** from Project Settings into `docker-compose.yml` (section 8). It is an identifier, not a secret.
6. In the repo, run `infisical init`, pick the project, and commit the `.infisical.json` it creates. This is what lets every developer skip that step.
7. Add each developer to the project with access to `local`.

### One identity per project

**Why one.** On our self-hosted Infisical an identity cannot be limited to a single environment: both ways of doing that, custom roles and additional privileges, need an enterprise license. Any identity added to a project can read all of that project's environments, so three identities would be no safer than one. Each project therefore has one project-level identity, shared by its three Coolify applications. It cannot read any other project.

**The guard that comes with it.** With a shared identity, the `INFISICAL_ENV` field in Coolify is the only thing deciding which values a container receives. A wrong value there would start Develop on Production values without any error. To make that visible, every environment holds an `APP_ENV` variable equal to its own slug, and `/health/ready` returns it (section 11). Check it whenever an application is created or its variables are edited.

**When an environment moves to its own server.** A second identity in the same project would not isolate it, for the reason above: the identity left on the shared server could still read the moved environment's values. The boundary that does hold is the project. So when an environment, usually Production, moves to its own server:

1. Create a separate Infisical project for it, named `<repo>-<env>` (for example `orderdesk-api-prod`), and move that environment's values into it.
2. Create a project-level identity in the new project and use its Client ID and Client Secret on the new server.
3. In `docker-compose.yml`, change the project ID line to `${INFISICAL_PROJECT_ID:-<current id>}` and set the new project's ID on the moved deployment.
4. Delete that environment's values from the original project.

After that, nothing on the shared server can read them.

**If we get an enterprise license.** Switch to one identity per environment, each restricted to its own environment. A wrong `INFISICAL_ENV` then fails at startup, and the `APP_ENV` guard is no longer needed.

### Developer guide: pulling the values to your machine

**Once per machine**

1. Ask the tech lead to add you to the project in Infisical.
2. Install the CLI.

   ```bash
   # macOS
   brew install infisical/get-cli/infisical

   # Ubuntu / Debian
   curl -1sLf 'https://artifacts-cli.infisical.com/setup.deb.sh' | sudo -E bash
   sudo apt-get update && sudo apt-get install -y infisical

   # Windows and others: https://infisical.com/docs/cli/install
   ```
3. Log in to our self-hosted Infisical. A browser window opens; approve the login there. Without `--domain` the CLI goes to Infisical Cloud, where our projects do not exist.

   ```bash
   infisical login --domain="https://infisical.example.com"
   ```

**Once per repo**

4. Clone the repo and go to its root folder. The committed `.infisical.json` already links the folder to the right project, so there is nothing to initialise.
5. Check that you can see the values. This prints the `local` variables as a table:

   ```bash
   infisical secrets --env=local
   ```

**Every time you work**

6. Start the project. This pulls the `local` values and starts the containers:

   ```bash
   make dev
   ```

   Underneath, `make dev` runs the command below and then `docker compose up --build`. You can run it yourself whenever you only want the file:

   ```bash
   infisical export --env=local --format=dotenv --output-file=.env
   ```
7. Stop with `make down`. It also deletes the `.env`.

**Good to know**

- The `.env` is a snapshot. When someone changes a value in Infisical, run `make dev` again to pick it up.
- To run one command with the values and no file at all: `infisical run --env=local -- <command>`.
- To reproduce a bug from a server, pull that environment instead, if you have access: `make dev ENV=staging`.
- To add or change a variable, edit it in Infisical in all four environments and update `.env.example`. Never send secrets over Slack or email.
- If you need a different value only on your own machine, add a personal override for it in Infisical. The export picks it up for you and nobody else.

**When it does not work**

| What you see | Likely cause | Fix |
|---|---|---|
| Asked to log in, or an authentication error | Your session expired | `infisical login` |
| "not yet connected this project" or asked to run `infisical init` | You are not in the repo root, or `.infisical.json` is missing | `cd` to the repo root. If the file is missing, the tech lead commits it (step 6 above) |
| A permission error, or the project is not listed | You have not been added to the project or to `local` | Ask the tech lead |
| The `.env` is empty or variables are missing | Wrong environment slug, or the values sit inside a folder | Check the slug in Project Settings. For a folder, add `--path="/folder"` |
| "unknown flag: --output-file" | Old CLI | Update the CLI (`brew upgrade infisical`) |
| The login opens Infisical Cloud instead of our server | The CLI defaults to Cloud | `infisical login --domain="https://infisical.example.com"` |

## 8. Run the project: Dockerfile, entrypoint, Compose and Makefile

Four files work together. Each has one job.

| File | Its job | Who uses it |
|---|---|---|
| `Dockerfile` | How to build the image | Docker, on a laptop and on Coolify |
| `scripts/entrypoint.sh` | The first thing that runs inside the container: make sure the app has its values, then start it | Every container, everywhere, because it is built into the image |
| `docker-compose.yml` | What runs: which services, built from what, with which variables | Coolify, and `make dev` |
| `Makefile` | Short commands so nobody has to remember long ones | Developers only. Coolify never runs `make` |

The Makefile does not replace Compose. `make dev` pulls the values from Infisical and then calls `docker compose up` for you.

**Where the values come from**

Infisical is the source in both places. Only the delivery differs.

| | On your laptop | On Coolify |
|---|---|---|
| Who pulls from Infisical | You. `make dev` runs `infisical export --env=local` under your own login | The container. `entrypoint.sh` logs in with the machine identity |
| How the values reach the app | Written to a generated `.env`, which Compose hands to the container | Injected straight into the app process when it starts |
| What `entrypoint.sh` does | Sees no machine identity, so it starts the app with the values it was given | Fetches the values, then starts the app |

The `.env` is a generated copy, never a source. Nobody edits it by hand: change the value in Infisical and run `make dev` again. It is git-ignored and `make down` deletes it.

### Dockerfile

Write it so that a code change rebuilds only the last step, and a change to a value in Infisical rebuilds nothing.

1. **Order it from slowest and most stable to fastest and most changed.** Base image and system packages, then dependency manifests, then dependency installation, then the source code. Docker reuses every layer above the first line that changed.
2. **Copy dependency manifests before the source.** `COPY requirements.txt` (or `package*.json`) and install, and only then `COPY . .`.
3. **Keep a `.dockerignore`.** Exclude `.git`, `node_modules`, `.env*`, `docs` and local caches so unrelated files do not invalidate the source layer.
4. **Pass nothing from the environment at build time.** No secrets, no URLs, no per-environment build arguments. The image is identical for Dev, Staging and Production, and values arrive when the container starts. This is what turns a changed value into a restart instead of a build.
5. **Pin the base image version** so the early layers stay cached.

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim

# 1. System packages and the Infisical CLI. Changes almost never.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl ca-certificates \
    && curl -1sLf 'https://artifacts-cli.infisical.com/setup.deb.sh' | bash \
    && apt-get update \
    && apt-get install -y --no-install-recommends infisical \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Dependencies. Rebuilt only when requirements.txt changes.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# 3. Source code. The only layer a normal code change rebuilds.
COPY . .

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail http://localhost:8000/health/ready || exit 1

ENTRYPOINT ["./scripts/entrypoint.sh"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Frontends are the exception to rule 4.** Values such as `VITE_*` or `NEXT_PUBLIC_*` are compiled into the JavaScript bundle, so changing one needs a rebuild. Keep them few and rely on the cached dependency layer to keep that rebuild short.

### scripts/entrypoint.sh

Commit it as executable (`chmod +x scripts/entrypoint.sh`).

```sh
#!/bin/sh
set -e

# No machine identity: a local run. `make dev` already supplied the values.
if [ -z "$INFISICAL_CLIENT_ID" ]; then
  exec "$@"
fi

# Deployed: log in as the machine identity, fetch the values for this
# environment and start the app with them.
INFISICAL_TOKEN=$(infisical login --method=universal-auth \
  --client-id="$INFISICAL_CLIENT_ID" \
  --client-secret="$INFISICAL_CLIENT_SECRET" \
  --plain --silent)
export INFISICAL_TOKEN

exec infisical run --projectId="$INFISICAL_PROJECT_ID" --env="$INFISICAL_ENV" -- "$@"
```

### docker-compose.yml

This is the file Coolify deploys. It lists the services and the few variables the entrypoint needs on a server.

```yaml
# docker-compose.yml
services:
  app:
    build: .
    restart: unless-stopped
    environment:
      INFISICAL_PROJECT_ID: 00000000-0000-0000-0000-000000000000   # from section 7; not a secret
      INFISICAL_DOMAIN: https://infisical.example.com              # our self-hosted Infisical; required
      INFISICAL_ENV: ${INFISICAL_ENV:-}                            # dev, staging or prod; set in Coolify
      INFISICAL_CLIENT_ID: ${INFISICAL_CLIENT_ID:-}                # set in Coolify, empty on a laptop
      INFISICAL_CLIENT_SECRET: ${INFISICAL_CLIENT_SECRET:-}        # set in Coolify, empty on a laptop
      APP_COMMIT: ${APP_COMMIT:-local}
```

A project with several services (backend, frontend, worker) gives each service the same block. Each image uses the same entrypoint.

### docker-compose.override.yml

**What it is.** Docker Compose's built-in way to keep laptop-only settings out of the file that gets deployed. Whenever you run `docker compose` in the project folder, Compose reads `docker-compose.yml` and then, if it exists, `docker-compose.override.yml`, and lays the second on top of the first. No flag is needed. Coolify is pointed at `docker-compose.yml` only, so nothing in the override ever reaches a server.

| | Reads `docker-compose.yml` | Reads `docker-compose.override.yml` |
|---|---|---|
| `make dev` on a laptop | Yes | Yes, automatically |
| Coolify | Yes | No |

**What goes in it.** Start with the two things every project needs locally:

```yaml
# docker-compose.override.yml
services:
  app:
    env_file:
      - path: .env        # generated from Infisical by `make dev`
        required: false
    ports:
      - "8000:8000"       # reach the app at http://localhost:8000
```

Neither belongs in the main file. On Coolify the values come through the entrypoint, traffic arrives through Coolify's proxy, and a published port would collide as soon as two environments share a server.

**How to use it.**

1. **You never run it yourself.** `make dev` runs `docker compose up`, and Compose picks the file up.
2. **Deciding where a setting goes:** if a server needs it, it goes in `docker-compose.yml`. If it only makes sense on a laptop, it goes in the override.
3. **Write only what differs.** Name the same service and add just the keys you are adding or changing. Lists such as `ports` and `environment` are combined with the main file; single values such as `command` are replaced.
4. **Commit it.** It contains no secrets, and everyone on the project gets the same local setup.
5. **Check the result** with `docker compose config`, which prints the merged definition. `docker compose -f docker-compose.yml config` prints what Coolify sees.

**Common additions.** These are the usual reasons the file grows:

```yaml
services:
  app:
    volumes:
      - ./src:/app/src        # edit code and see it without rebuilding the image
    command: uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
    environment:
      # A value set here wins over the same name in .env.
      DATABASE_URL: postgresql://postgres:postgres@db:5432/app

  db:                          # a local database, so you are not sharing the Dev one
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: app
    ports:
      - "5432:5432"
```

### Makefile

One Makefile, four commands.

```makefile
ENV ?= local

.PHONY: setup dev down lint

setup:  ## once per clone: install the commit hooks and log in to Infisical
	pre-commit install
	infisical login

dev:    ## pull the values for ENV from Infisical, then build and start everything
	infisical export --env=$(ENV) --format=dotenv --output-file=.env
	docker compose up --build

down:   ## stop everything and delete the generated .env
	docker compose down
	rm -f .env

lint:   ## run every check on every file (the same checks that run on commit)
	pre-commit run --all-files
```

- `make dev ENV=staging` runs the same code against Staging values when you need to reproduce a Staging bug.
- `.env` holds real values while the project is running. It must be listed in `.gitignore` and `.dockerignore`.
- What `make lint` checks is defined in `.pre-commit-config.yaml` (section 10).

## 9. Deploy with Coolify

Each environment is one Coolify application built from the repo's `docker-compose.yml`.

1. **Create the applications.** In the Coolify project, use one environment per branch (`develop`, `staging`, `production`) and add one application to each. Source: the repo through the GitHub App, on the matching branch. Build pack: **Docker Compose**. Docker Compose Location: `/docker-compose.yml`.
2. **Set the domain** for each public service under Domains, including the port the container listens on, for example `https://dev.orderdesk.example.com:8000`.
3. **Fill in the environment variables.** Open Environment Variables. Coolify has already listed the variables named in the Compose file. Enter:

   | Variable | Value |
   |---|---|
   | `INFISICAL_CLIENT_ID` | Client ID of the project's machine identity. The same in all three applications |
   | `INFISICAL_CLIENT_SECRET` | Its client secret. The same in all three applications |
   | `INFISICAL_ENV` | `dev`, `staging` or `prod`. The only value that differs between the three, so check it twice |
   | `APP_COMMIT` | `$SOURCE_COMMIT` |

   The list shows a **Buildtime** and a **Runtime** column for every variable. Use the gear icon at the end of each row to switch **Buildtime off** and keep **Runtime on**. Rows marked **Managed** (`SERVICE_FQDN_*`, `SERVICE_URL_*`) are generated by Coolify; leave them alone. Nothing else belongs on this page: any other variable goes into Infisical.
4. **Turn on Auto Deploy** under Advanced (Git or Deployment, depending on the Coolify version). A merge into the branch then deploys its environment.
5. **Leave "Include Source Commit in Build" off** under Advanced → Build. It is off by default, and turning it on would break the layer cache on every commit.
6. **Health check.** Compose applications do not use Coolify's Healthcheck page. The `HEALTHCHECK` in the Dockerfile is what changes the status from "Running (no healthcheck)" to healthy.
7. **Confirm the environment.** After the first deploy of each application, open its `/health/ready` and check that `environment` shows `dev`, `staging` or `prod` as expected. All three applications use the same identity, so this is how a wrong `INFISICAL_ENV` is caught.

| What changed | What to do | What happens |
|---|---|---|
| Code | Merge the PR | Auto deploy; cached layers are reused and only the source layer rebuilds |
| Dependencies | Merge the PR | Rebuild from the dependency layer down |
| A value in Infisical | Actions → Restart on the application | No build. The container restarts and fetches the new values |

If builds are slow for no clear reason, check the server's Docker clean-up settings. An aggressive clean-up deletes the build cache.

## 10. Code checks: on commit and on pull request

The same checks run at two points. On your machine they stop a bad commit before it exists. On GitHub they stop a PR from merging. Both read one file, `.pre-commit-config.yaml`, so there is a single definition of "lint".

| When | What runs it | Can it be skipped? |
|---|---|---|
| Every `git commit` | The pre-commit hook installed by `make setup` | Yes, with `git commit --no-verify` |
| Any time | `make lint` | It is manual |
| Every PR into `develop`, `staging` or `main` | GitHub Actions | No. It is a required check |

### On commit: pre-commit hooks

Install the tool once per machine (`brew install pre-commit` or `pipx install pre-commit`), then run `make setup` in each clone. From then on a commit is refused until the checks pass. Hooks that can fix a file do so; stage the fixed file and commit again.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-merge-conflict
      - id: check-added-large-files
      - id: detect-private-key

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.22
    hooks:
      - id: ruff-check        # lint, fixing what it safely can
        args: [--fix]
      - id: ruff-format       # format

  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks          # refuse commits that contain secrets
```

- Run `pre-commit autoupdate` after adding the file, and every few months, to move the `rev` values to the latest releases.
- The hooks run in their own isolated environments. Nothing has to be installed in the project for them to work.
- For a Node project, replace the Ruff block with a local hook that calls the project's own linter:

  ```yaml
  - repo: local
    hooks:
      - id: eslint
        name: eslint
        entry: npx eslint --max-warnings=0
        language: system
        files: \.(js|jsx|ts|tsx)$
  ```

### On pull request: GitHub Actions

Coolify deploys; it does not judge a pull request. GitHub Actions is used only for checks that must pass before a PR merges, and only for PRs into `develop`, `staging` and `main`. Start with this one workflow. Its two jobs are the checks the `required-checks` ruleset (section 6) makes mandatory.

```yaml
# .github/workflows/pr-checks.yml
name: pr-checks
on:
  pull_request:
    branches: [develop, staging, main]
    types: [opened, synchronize, reopened]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run the same hooks developers run on commit
        run: pipx run pre-commit run --all-files

  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Image builds
        run: docker compose build
```

The `lint` job is what makes the hooks binding: a commit made with `--no-verify` still fails here. The `build` job proves the Dockerfile builds before anything reaches Coolify.

**Ideas for later.** Add these as extra hooks or extra jobs in the same two files when a project needs them. They are suggestions, not requirements.

| Check | What it catches | Where it fits |
|---|---|---|
| Type check (`mypy`, `tsc --noEmit`) | Type errors the linter misses | Hook or job |
| Branch name on push | A badly named branch before the PR is opened | Hook (`pre-push` stage) |
| Leftover debug code | `print`, `console.log` or `debugger` in changed files | Hook |
| `.env.example` in sync | A variable the code reads that is missing from `.env.example` | Hook or job |
| Compose file valid (`docker compose config -q`) | A broken `docker-compose.yml` before Coolify finds it | Job |
| Promotion direction | A PR into `main` that does not come from `staging` or `hotfix/*`; a PR into `staging` that does not come from `develop` or `fix/*` | Job |
| PR size | A warning or label when a PR passes 400 changed lines | Job |
| Docker layer cache in CI | Not a check: speeds up the `build` job once builds get slow | Job |
| Back-merge reminder | Opens the back-merge PR automatically after a fix lands on `staging` or `main` | Separate trigger, later |
| Stale branches | A weekly list of branches older than two weeks | Scheduled, later |

CodeRabbit also runs linters and secret scanners inside its review, but it reports them as comments. Use hooks and Actions for anything that must block.

## 11. Add health checks

Every backend service exposes two unauthenticated endpoints:

| Endpoint | Answers | Checks | Returns |
|---|---|---|---|
| `GET /health/live` | Is the process running? | Nothing external | `200` always |
| `GET /health/ready` | Can it serve requests? | Database, cache, queue, critical internal services | `200`, or `503` if any dependency fails |

```json
{
  "status": "ok",
  "environment": "staging",
  "commit": "a1b2c3d",
  "checks": { "database": "ok", "redis": "ok" }
}
```

- Return the environment (from `APP_ENV`, which comes out of Infisical) so anyone can confirm the application loaded the right set of values.
- Return the deployed commit (from `APP_COMMIT`) so anyone can confirm what is running.
- Respond in under a second. Put a timeout on every dependency check.
- Expose no secrets, hostnames or stack traces.
- Do not call paid or rate-limited third-party APIs from a health check.
- `/health/ready` is the Dockerfile `HEALTHCHECK`, so a deploy that does not turn healthy is visible in Coolify immediately.
- Frontends serve a static `/version.json` containing the commit.

## 12. Connect CodeRabbit

Follow "Per-project setup" in the [CodeRabbit standard](coderabbit.md).

## 13. Baseline standards

| Area | Standard |
|---|---|
| Config and secrets | All configuration through environment variables, stored in Infisical. `.env.example` lists every name. No real value is ever committed. |
| Local run | `make setup` once, then `make dev`, from a clean clone. |
| Make targets | `setup`, `dev`, `down` and `lint` exist in every repo with the same meaning. |
| Code checks | Defined once in `.pre-commit-config.yaml`; run on every commit and again on every PR. |
| Logging | Logging is there from the first commit and at every step: each request, background job, external call and error is logged. |
| API documentation | OpenAPI generated from the code and served at `/docs` on Dev and Staging. |

## 14. Setup checklist

Copy into the project's setup task.

```markdown
- [ ] Repo created in the org, named `<project>-<component>`, private, description set
- [ ] Teams granted access (no individual collaborators)
- [ ] `develop` and `staging` created; `develop` is the default branch
- [ ] Standard files added (section 3), including PR template, AGENTS.md and .editorconfig
- [ ] README complete; a teammate ran the project from it on a clean machine
- [ ] Merge settings configured; auto-delete head branches on
- [ ] Three rulesets imported; a direct push to `develop` was tried and rejected
- [ ] Infisical project created with `local`, `dev`, `staging`, `prod`; `.infisical.json` committed
- [ ] One project-level machine identity (`<repo>-coolify`); developers have access to `local`
- [ ] `APP_ENV` set in all four Infisical environments
- [ ] Project ID set in `docker-compose.yml`
- [ ] `.env` is in `.gitignore` and `.dockerignore`
- [ ] `make setup`, `make dev`, `make down` and `make lint` work on a clean clone
- [ ] `.pre-commit-config.yaml` added; a commit with a lint error was tried and refused
- [ ] Dockerfile follows the layer order in section 8; a second build of unchanged code is fast
- [ ] Coolify applications created for Dev, Staging and Production with the Docker Compose build pack
- [ ] Coolify holds only `INFISICAL_CLIENT_ID`, `INFISICAL_CLIENT_SECRET`, `INFISICAL_ENV` and `APP_COMMIT`, all with Buildtime off
- [ ] Changing a value in Infisical and restarting updates the app without a build
- [ ] PR checks workflow added for `develop`, `staging` and `main`; `required-checks` ruleset switched to Active after its first run
- [ ] `/health/live` and `/health/ready` implemented; Coolify shows the app as healthy
- [ ] `/health/ready` on Dev, Staging and Production each reports its own environment
- [ ] CodeRabbit configured; a test PR received a review
```
