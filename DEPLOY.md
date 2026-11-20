# Deploying to Vercel

The app is **one Vercel project with two services**, both defined in `vercel.json`:

| Service | Folder | Public paths | What it is |
|---|---|---|---|
| `web` | `frontend` | everything not listed below (`/`, assets) | the Vite/React site |
| `api` | `.` (repo root) | `/api/*`, `/login`, `/health` | FastAPI from `main:app` |

Because both are served from the same address, the site calls the API at the same origin:
no `VITE_API_URL`, no `CORS_ORIGINS`. The API's other routes (`/`, `/protected`, `/docs`) are not
exposed publicly. There are no service-to-service calls, so `vercel.json` has no `bindings`.

**No secrets are stored in the repository.** They live only in your local `.env` and in
Vercel's *Settings → Environment Variables*.

## 1. Generate your secrets locally (once)

```
# JWT signing key (copy the output; don't save it in any file in the repo)
python -c "import secrets; print(secrets.token_urlsafe(64))"

# Login account: prints {"username": "<argon2 hash>"} - only the hash, never the password
python database/users.py hash <username>
```

## 2. Create the project

1. Vercel dashboard → **Add New → Project** → import this GitHub repo (pick the branch you want
   as production in *Settings → Git*).
2. **Root Directory:** `.` (leave as is). **Framework Preset:** choose **Services**
   (Vercel reads `vercel.json`).
3. **Environment Variables** (apply to all services):

| Name | Value |
|---|---|
| `JWT_SECRET_KEY` | the key from step 1 |
| `APP_USERS` | the JSON line from step 1 (several users: `{"a": "<hash>", "b": "<hash>"}`) |

4. Deploy, then open `https://<your-project>.vercel.app/health`. You should see
   `{"status":"healthy"}`. Open the site root and log in.

## Updating the hosted site

- **Code or retrained model:** commit and push. Vercel redeploys automatically (the production
  branch goes live; other branches get preview URLs). After retraining, commit the new files in
  `ml/outputs/` (`predictions.csv` and `model_metrics.csv` are what the API loads).
- **Add or change a login:** generate a new hash (step 1), update `APP_USERS`, redeploy.
- **Rotate the JWT key:** change `JWT_SECRET_KEY` and redeploy. Everyone has to log in again.

## How the hosted API works (and its limits)

Vercel's filesystem is read-only and doesn't persist between servers, so the API builds its
SQLite database in `/tmp` from the CSVs in the repo each time a server starts (about 1 second;
`database/bootstrap.py`). It is read-only data. Anything written at runtime (new accounts,
password changes) is lost, which is why accounts come from `APP_USERS`.

These repo files must stay committed or the hosted API has no data:
`data_cleaning/wastewater_costs_2017_2025_checked.csv`, `ml/outputs/predictions.csv`,
`ml/outputs/model_metrics.csv`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Site loads but login says "Can't reach the server" | `/login` or `/api/*` isn't routed to the `api` service: check `vercel.json` is at the repo root and the project uses the Services preset |
| `/health` returns the site's HTML instead of JSON | same as above |
| API error at startup: `JWT_SECRET_KEY environment variable is not set` | add it in Environment Variables and redeploy |
| API error: `APP_USERS ... Argon2 hash` | the value was a plain password or invalid JSON; regenerate with `python database/users.py hash <username>` |
| Login says invalid username or password | `APP_USERS` is missing or has a different username |
| First request after being idle takes a few seconds | normal wake-up of an idle server |

## Local development is unchanged

```
pip install -r requirements-ml.txt     # API + data pipeline + ML (requirements.txt is API-only)
python database/load_sqlite.py         # builds database/wastewater.db (also happens automatically if missing)
python database/users.py add <username>
uvicorn main:app --reload
cd frontend && npm install && npm run dev      # talks to http://127.0.0.1:8000
```

`requirements.txt` is deliberately small: it is what Vercel installs for the API, and the ML
packages alone (~600 MB) would exceed Vercel's 500 MB function limit.
