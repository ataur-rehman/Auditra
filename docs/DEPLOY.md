# Deploying Auditra: Railway, Vercel and the Windows agent

```
employee laptop                         Railway                         Vercel
AuditraAgent (SYSTEM) --HTTPS-->  Django API + Postgres  <--HTTPS--  React console
(outbox, every 3 s)               /api/agent/*, /api/live/           (polls /api/live/ every 2 s)
```

An action on a laptop reaches the officer's screen in about 5 seconds:
- the agent collects every 3 s and sends straight away;
- the console polls every 2 s.

If the API cannot be reached, the agent keeps events in its outbox and sends them, oldest first, when it is back.

## 1. Railway: API and database

1. Create a project, add **PostgreSQL**, then add an empty service, for example `auditra-api`. With the CLI:
   ```bash
   railway init --name auditra
   railway add --database postgres
   railway add --service auditra-api
   ```
2. Deploy the `backend` folder: run `railway up --service auditra-api` from inside `backend`. Alternatively, connect the GitHub repository with **Root Directory** `backend`.

   `backend/railpack.json` sets the start command: migrate, create the first logins, collectstatic, then gunicorn. Railway's builder reads it directly. (`railway.json` Config as Code is deprecated and is not read by new projects.)

   Gunicorn runs **one worker with 8 threads**, so the minute-by-minute compliance job runs once. Do not raise the number of workers.
3. **Variables** on the API service:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (Railway reference) |
   | `SECRET_KEY` | a long random string, for example `python -c "import secrets;print(secrets.token_urlsafe(50))"` |
   | `INGEST_API_KEY` | a long random string (only business systems posting to `/api/decisions/` use it) |
   | `CORS_ALLOWED_ORIGINS` | `https://<your-app>.vercel.app` |
   | `ADMIN_PASSWORD`, `OFFICER_PASSWORD` | the first passwords for `admin` and `compliance_officer` |
   | `TIME_ZONE` | `Asia/Karachi` (default) |
   | `AGENT_DOWNLOAD_URL` | where the portal's and admin pages' download button points: a direct download link to `AuditraAgent.exe` |

   Some values are set without you:
   - Railway sets `RAILWAY_ENVIRONMENT` and `RAILWAY_PUBLIC_DOMAIN`. With them, `DEBUG` is off and the public domain is allowed automatically.
   - The app refuses to start if `SECRET_KEY` or `INGEST_API_KEY` is missing or still the development value.
   - The shared-key agent registration (`AGENT_KEY_ENROLMENT`) is off in production. Laptops enrol with one-time codes.
4. **Settings > Networking > Generate Domain**, for example `auditra-api.up.railway.app`.
5. The start command also runs `create_default_users`. On the first deploy it creates `admin` and `compliance_officer` from `ADMIN_PASSWORD` and `OFFICER_PASSWORD`; afterwards it does nothing.
   - If those passwords are missing, the first deploy stops with a clear message.
   - Change the passwords later under Admin > Console Users. The variables are only read the first time.
   - Lost the admin password? Set `RESET_DEFAULT_PASSWORDS=true`, let it deploy, sign in, then delete the variable.
   - When setting variables from a script on Windows, strip `\r` from the values: a trailing carriage return becomes part of the secret.

## 2. Vercel: console

1. Import the repository and set **Root Directory** to `frontend`. Vite is detected. `frontend/vercel.json` sends every route to `index.html`, so reloading `/incidents/...` works.
2. Environment variable: `VITE_API_URL` = `https://auditra-api.up.railway.app/api`. It is read at build time, so redeploy after changing it.
3. Put the Vercel production URL in Railway's `CORS_ALLOWED_ORIGINS`.
4. **Settings > Deployment Protection**: turn **Vercel Authentication** off. New Vercel projects have it on, which puts a Vercel sign-in in front of the console; officers and employees sign in to Auditra itself.

## 3. The agent installer

On a Windows machine with Python:
```powershell
powershell -ExecutionPolicy Bypass -File agent\build.ps1 -Server https://auditra-api.up.railway.app -Release
```
- This builds `agent\dist\AuditraAgent.exe`.
- `-Server` is only the pre-filled address; no secret is built into the exe.
- Host the exe where anyone can download it without signing in, and set `AGENT_DOWNLOAD_URL` on Railway to the direct link.
- With Google Drive, share the file as "Anyone with the link". Do not use the `/view` link: use `https://drive.usercontent.google.com/download?id=<file id>&export=download&confirm=t`. The ordinary `uc?export=download` link stops at Drive's "can't scan this file for viruses" page.
- Replacing the file on Drive with **Manage versions** keeps the same id, so the link keeps working.

## 4. Onboarding an employee

1. **Admin > Employees & Access**: add the employee, then click the person icon to create their portal login. The temporary password is shown once.
2. The employee signs in at the Vercel URL and lands on their portal. There they:
   1. read the monitoring notice and click **I have read the notice**;
   2. download `AuditraAgent.exe`;
   3. click **Get enrolment code**. The code is valid for 30 minutes and works once.
3. **Signed in to Windows as themselves**, they double-click `AuditraAgent.exe` on the laptop. The installer links whichever Windows account is at the screen; if an IT person installs it from their own session, IT's account is linked instead.
   1. Windows asks for administrator approval. On a standard account, IT types an admin password: that is the permission step.
   2. They enter the code.
4. The agent then:
   - enrols the laptop to that employee and links the signed-in Windows account;
   - turns on the audit policy, file auditing on the catalogue folders, the print log and a 256 MB Security log;
   - sets the Windows sign-in notice;
   - registers the agent in Task Scheduler (runs as SYSTEM at boot, restarted if it stops).
5. **Admin > Agents & Health** shows the laptop, its owner, and every Windows check. A red check names what is wrong and how to fix it.

To issue a code without a portal login, use the key icon on the employee's row.

**Notes**
- Uninstall from *Settings > Apps > Auditra Agent*, or run `AuditraAgent.exe uninstall`. It restores the audit policy and sign-in notice that were there before.
- On a domain laptop, Group Policy can switch the audit policy back. The agent reports this as a failed check, and only the domain administrator can fix it.
- Firefox history is not read; Chrome, Edge and Brave are.

## 5. Going back to the LAN setup (demo-day fallback)

Nothing above removes the two-laptop setup in the README.
1. Run the API with `DEBUG=true` (the default when not on Railway).
2. Build the exe with `-Server http://<laptop-IP>:8000`.
3. Enrol it with a code from the local console.

`python -m auditra_agent run` with `AUDITRA_ENROLMENT_KEY` set still works against a local server for development.
