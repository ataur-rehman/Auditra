# Auditra

Auditra is a GDPR compliance monitor. A Windows agent on each employee laptop sends a small set of clean, structured events. The server maps each event to the GDPR articles it may breach and scores it out of 100, adding an anomaly score learned from CERT data. The compliance officer sees the incident within seconds, with the evidence and the actions to take.

Nothing in the console is simulated. Every event comes from a real machine. Every employee, folder, consent record and request is entered through the console.

Detection scope is the team's workbook `Auditra_GDPR_Violation_Mapping.xlsx`: 22 articles, the USB events and the other actions, 41 rules in all. The design is in [docs/superpowers/specs](docs/superpowers/specs/2026-10-22-live-monitoring-design.md).

## Parts

| Part | Where | What it does |
|---|---|---|
| Agent | `agent/` | A background agent (`AuditraAgent.exe`, run by Task Scheduler as SYSTEM). Reads the Security, Plug and Play and PrintService logs, plus copies to USB drives, visits to watched sites in Chrome and Edge, and file ages. It sends only structured events, keeps them in a local outbox while the server is unreachable, and switches on the Windows auditing it needs itself. |
| API | `backend/` (Django + DRF, Postgres) | Ingest, rules (`compliance/detection/`), score (`scoring.py`), AI (`ai.py`), and the officer and admin API |
| Console | `frontend/` (React, Vite, Tailwind) | Officer and admin views with a live feed, polled every 2 s, and an employee portal for the monitoring notice and laptop enrolment. Light and dark themes. |
| ML research | `ml_pipeline_cert/` | The CERT r4.2 pipeline: 4 models evaluated, OCSVM exported. Its baselines feed `ai.py`. |

## First-time setup (server laptop)

```powershell
# Postgres: database auditra_db, user auditra_user / auditra123 (see .env.example)
cd backend
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py create_default_users
cd ..\frontend
npm install
```

The login accounts come from `create_default_users`. Change their passwords under Admin > Console Users.

To host it on Railway (API and Postgres) and Vercel (console), and to install the agent on employee laptops, follow [docs/DEPLOY.md](docs/DEPLOY.md).

## Demo day: two laptops

**Laptop B** runs the server and the agent, and is the employee's machine. **Laptop A** is the officer and only needs a browser. Join both to the same phone hotspot.

1. **Laptop B, once:** open PowerShell with *Run as administrator* and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\windows\setup_demo_machine.ps1
   powershell -ExecutionPolicy Bypass -File scripts\windows\setup_server_firewall.ps1
   ```
   - The first script turns on Windows auditing, creates `C:\AuditraCompany` with its department folders, adds file-access auditing, turns on the print log and the lockout policy, and creates the local employee account `bilal`.
   - The second opens ports 8000 and 5173 and prints this laptop's address.
   - Undo everything with `undo_demo_machine.ps1`.
   - Sign in as `bilal` once so Windows creates the profile.
2. **Laptop B, start the server and the console:**
   ```powershell
   cd backend;  python manage.py runserver 0.0.0.0:8000
   cd frontend; npm run dev
   ```
3. **Laptop B, install the agent once.**
   1. Build it: `powershell -ExecutionPolicy Bypass -File agent\build.ps1 -Server http://<laptop-B-ip>:8000`.
   2. In the console, open **Admin > Employees & Access** and click the key icon on Bilal's row to get an enrolment code.
   3. Double-click `agent\dist\AuditraAgent.exe`, approve the administrator prompt and type the code.

   It registers the agent in Task Scheduler as SYSTEM, so it starts with Windows. For a rehearsal that prints every event, run `"C:\Program Files\Auditra\AuditraAgent.exe" stop`, then `cd agent; python -m auditra_agent run` in an Administrator PowerShell.
4. **Laptop A:** open `http://<laptop-B-ip>:5173` and sign in.
5. **Configure the organisation live, as admin.** This is real configuration, not seed data.
   - **Data Catalogue:** add `C:\AuditraCompany\Finance` (FINANCIAL, MEDIUM), `Payroll` (FINANCIAL, HIGH), `HR` (HR_EMPLOYEE, HIGH), `HR\employees_cnic.csv` (NATIONAL_ID, HIGH), `Medical` (HEALTH, HIGH), `Legal` (CRIMINAL, HIGH), `Customers` (CUSTOMER, MEDIUM) and `Biometrics` (BIOMETRIC, HIGH). Link each one to a processing activity, which you create in GDPR Records > Processing.
   - **Employees & Access:** add Bilal Ahmed, Finance, Staff, shift 09:00–18:00, up to MEDIUM, categories FINANCIAL and CUSTOMER. Link the account `MACBOOK\bilal`, or use *Accounts seen by agents* once he has logged on.
   - **GDPR Records:** add the data subject Ali Khan with the path `C:\AuditraCompany\Customers\ali_khan_profile.csv`, a consent record, and the DPO.
   - Admin > Agents & Health shows the agent online with each collector's status.

Before the presentation, check three things:
- Bilal's shift covers the presentation time, or scene 2 is a HIGH violation, not a LOW indicator.
- Bilal signs in with a password, not a Windows Hello PIN, so scene 9 produces failed-logon events.
- Laptop B is set to never sleep while plugged in.

Sign in on laptop A as **admin**: the admin sees every officer page and can also change shifts and consent live.

### Scenes (do them on laptop B as `bilal`; laptop A shows each within about 10 seconds)

| # | Bilal does | Officer sees |
|---|---|---|
| 1 | Opens `Finance\invoices_2026.csv` | An activity row only, with no incident: the false-positive check |
| 2 | Plugs in a USB stick during the shift | A LOW risk indicator (Art. 32) |
| 3 | Opens `Payroll\salaries_2026.csv` | **Art. 25**, access beyond his role |
| 4 | Opens `Medical\patient_records.csv` | **Art. 9**, special-category data, CRITICAL |
| 5 | On laptop A, signed in as admin, open Employees & Access and set Bilal's shift to end now. Bilal then copies `HR\employees_cnic.csv` to the USB stick | **Art. 32, 5(1)(f), 87, 25**, CRITICAL, with the score breakdown and the AI points |
| 6 | Opens `Customers\ali_khan_profile.csv` after the officer withdraws Ali's consent | **Art. 7**, CRITICAL |
| 7 | Deletes `leads_1.csv`, `leads_2.csv` and `leads_3.csv` in `Customers` (run the setup script again to restore them) | **Mass deletion**, Art. 32 and 5(1)(f) |
| 8 | Opens wetransfer.com after scene 6 | Possible upload of personal data, Art. 32 and 5 |
| 9 | Locks with Win+L and types a wrong password 5 times, then the right one | **Brute force**, Art. 32. A 6th wrong password instead locks the account for 5 minutes (lockout indicator). |
| 10 | Prints `Customers\fatima_noor_profile.csv` to "Microsoft Print to PDF" | Print indicator |
| 11 | In an admin prompt: `net user temp1 P@ss12345 /add`, then `net localgroup administrators temp1 /add` | **Art. 25 and 32** account and privilege changes |

After 3 violations in 7 days, every new score gains the **Art. 83** escalation. Officer actions are written to the audit trail: investigate, escalate, resolve, mark false positive, and report a lost device (which opens a breach record with the 72-hour clock). To rehearse again, use Admin > Agents & Health > *Reset activity*. It keeps the configuration.

## Score

Rule severity base (CRITICAL 70, HIGH 55, MEDIUM 35, LOW 15), then:
- +5 per extra article, up to 10
- +10 outside the shift
- +10 for special-category or national-ID data
- up to +15 from an AI score above 60
- +10 for Art. 83

The total is capped at 100. Every incident stores the list of points it received.

## AI score

The detector computes 8 features per employee per day (activity, logons, logons outside shift, weekend logons, machines, activity outside shift, copies to USB, USB connections).
- Each feature is compared with the CERT r4.2 training baseline of 1,000 employees and 208,167 days. After 5 days of history, it is compared with the employee's own baseline instead.
- The deviations combine into √Σz², mapped to 0–100. A deviation of 3 maps to 60, the alert line.
- The score can only rise when behaviour becomes riskier.

The exported One-Class SVM is kept as the research result. A behavioural smoke check showed it flattens out on extreme inputs: it gave an after-hours USB copy 51.7, below a normal day at 57.4. For that reason the console uses the explainable detector above.

## Tests

```powershell
cd backend
$env:DB_ENGINE="sqlite"; $env:DB_NAME=":memory:"; $env:AUDITRA_SCHEDULER="off"
python manage.py test compliance
```

The backend tests replay the exact agent payloads for every rule:
- a clean baseline with no false positives
- AI monotonicity
- the agent token flow
- officer actions and permissions
- the PDF report
- employee logins, the monitoring notice and code enrolment
- the production settings guard

The agent's own tests (outbox, parsing) run with `cd agent; python -m unittest discover -s tests -t .`.

## Useful commands

```powershell
python manage.py run_compliance_cycle      # deadline, breach and automated-decision rules now
python manage.py sync_rules                # re-create rules from compliance/rules_catalogue.py
python manage.py reset_monitoring_data     # delete recorded activity (add --all-config to wipe setup too)
```

Business systems report automated decisions (Art. 22) to `POST /api/decisions/` with the header `X-Auditra-Ingest-Key`.
