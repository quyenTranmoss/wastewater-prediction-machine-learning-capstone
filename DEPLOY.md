# Deploying to Vercel

The app is two Vercel projects created from this one repository:

| Project | Root Directory | What it serves |
|---|---|---|
| **API** (backend) | `.` (repo root) | FastAPI from `main.py` |
| **Web** (frontend) | `frontend` | the Vite/React site |

**No secrets are stored in the repository.** They live only in your local `.env` and in
Vercel's *Settings → Environment Variables*.

## 1. Generate your secrets locally (once)

```
# JWT signing key (copy the output; don't save it in any file in the repo)
python -c "import secrets; print(secrets.token_urlsafe(64))"

# Login account: prints {"username": "<argon2 hash>"} - only the hash, never the password
python database/users.py hash <username>
```

## 2. Create the API project

1. Vercel dashboard → **Add New → Project** → import this GitHub repo.
2. **Root Directory:** `.` (leave as is). Vercel detects the FastAPI app in `main.py`.
3. **Environment Variables:**

| Name | Value |
|---|---|
| `JWT_SECRET_KEY` | the key from step 1 |
| `APP_USERS` | the JSON line from step 1 (several users: `{"a": "<hash>", "b": "<hash>"}`) |
| `CORS_ORIGINS` | add in step 4, once you know the web address |

4. Deploy, then open `https://<your-api>.vercel.app/health`. You should see `{"status":"healthy"}`.

## 3. Create the web project

1. **Add New → Project** → import the **same** repo again.
2. **Root Directory:** `frontend`. Vercel detects Vite (build `npm run build`, output `dist`).
3. **Environment Variable:** `VITE_API_URL` = the API address from step 2
   (e.g. `https://<your-api>.vercel.app`).
4. Deploy.

`VITE_` variables are baked in when the site is built and are visible in the browser, so use
them for the API address only, never a secret. Changing one needs a redeploy.

## 4. Allow the web address to call the API

On the **API** project set `CORS_ORIGINS` to the web project's address, exactly as it appears in
the browser (e.g. `https://<your-web>.vercel.app`; several separated by commas), then
**redeploy the API**. Open the web address and log in.

Preview deployments get different addresses. To allow them, also set `CORS_ORIGIN_REGEX` on the
API to a pattern for *your* project only, e.g. `https://<your-web>-.*\.vercel\.app`.

## Updating the hosted site

- **Code or retrained model:** commit and push. Vercel redeploys automatically (the production
  branch goes live; other branches get preview URLs). After retraining, commit the new files in
  `ml/outputs/` (`predictions.csv` and `model_metrics.csv` are what the API loads).
- **Add or change a login:** generate a new hash (step 1), update `APP_USERS`, redeploy the API.
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
| "Can't reach the server" on login | `VITE_API_URL` missing or wrong (redeploy the web project after fixing), or `CORS_ORIGINS` doesn't match the web address exactly |
| Browser console shows a CORS error | `CORS_ORIGINS` not set / API not redeployed after setting it |
| API error at startup: `JWT_SECRET_KEY environment variable is not set` | add it in the API project's environment variables and redeploy |
| API error: `APP_USERS ... Argon2 hash` | the value was a plain password or invalid JSON; regenerate with `python database/users.py hash <username>` |
| Login says invalid username or password | `APP_USERS` is missing or has a different username |
| First request after being idle takes a few seconds | normal wake-up of an idle server |

## Local development is unchanged

```
pip install -r requirements-ml.txt     # API + data pipeline + ML (requirements.txt is API-only)
python database/load_sqlite.py         # builds database/wastewater.db (also happens automatically if missing)
python database/users.py add <username>
uvicorn main:app --reload
cd frontend && npm install && npm run dev
```

`requirements.txt` is deliberately small: it is what Vercel installs for the API, and the ML
packages alone (~600 MB) would exceed Vercel's 500 MB function limit.
