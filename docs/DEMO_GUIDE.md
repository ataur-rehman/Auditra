# Auditra demo guide: rehearsal on one laptop

This guide uses one laptop for everything. You act as **Bilal**, the monitored employee, and watch the officer console in a browser window next to you. On presentation day the steps are the same, except the console is open on the second laptop.

---

## 0. Accounts you will use

| Where | Username | Password | What for |
|---|---|---|---|
| Auditra console | `admin` | `Auditra@2026` | Administrator: sees every officer page and can change shifts, consent and rules |
| Auditra console | `compliance_officer` | `Auditra@2026` | Officer only: no admin menu |
| Windows | `ataur` (your normal account) | your password | Runs the server, the console and the agent |
| Windows | `bilal` | the password you chose in the setup script | The monitored employee: do every scene as him |

Change the console passwords before the real presentation, under Admin, Console Users.

---

## 1. Start everything (as `ataur`, once per rehearsal)

Open **three** PowerShell windows.

**Window 1: API server** (normal PowerShell)
```powershell
cd E:\Auditra\backend
python manage.py runserver 0.0.0.0:8000
```
Leave it running. It should end with `Starting development server at http://0.0.0.0:8000/`.

**Window 2: console** (normal PowerShell)
```powershell
cd E:\Auditra\frontend
npm run dev
```
Leave it running. It prints `Local: http://localhost:5173/`.

**Agent: installed once, runs in the background as SYSTEM.** It starts with Windows, so on demo day there is nothing to start.

To install it the first time, or again after `undo_demo_machine.ps1`:
1. In the console, open **Admin > Employees & Access** and click the key icon on Bilal's row (**Enrolment code**). Alternatively, give Bilal a portal login (person icon); he signs in, reads the notice and clicks **Get enrolment code**.
2. **Sign in to Windows as `bilal`**, then double-click `AuditraAgent.exe` (built with `agent\build.ps1 -Server http://<this laptop's IP>:8000`). The installer links whichever Windows account is at the screen to Bilal. Run it from `ataur` instead and your own activity is counted as Bilal's.
3. At the administrator prompt, type the `ataur` password. Then type the code and click **Install and start monitoring**.

The setup window lists each Windows setting it switched on.

**Rehearsal: watch every event in a window.** Use an *Administrator* PowerShell:
```powershell
& "C:\Program Files\Auditra\AuditraAgent.exe" stop
cd E:\Auditra\agent
python -m auditra_agent run
```
Every event is printed as a `>` line. Press Ctrl+C to stop, then run `& "C:\Program Files\Auditra\AuditraAgent.exe" start`.

The background agent writes its log to `C:\ProgramData\Auditra\logs\agent.log`.

If the server is down, the agent keeps events in `C:\ProgramData\Auditra\outbox.db` and sends them when it comes back.

> If Windows 1 and 2 say the port is already in use, a server from an earlier session is still running. Close the other window, or skip that step because it is already up.

**Check:** open `http://localhost:5173`, sign in as `admin`, and open **Admin > Agents & Health**. The laptop should show:
- a green dot;
- owner **Bilal Ahmed**;
- **Administrator**;
- the collectors `security, usb, usb_copy, print, web` all `ok`;
- the Windows checks all green: audit policy, file auditing, print log, Security log, sign-in notice and clock.

A red check names what is wrong and how to fix it.

---

## 2. Switch to the employee

1. Press **Win + L**, click **Other user**, and sign in as `bilal`. The first sign-in takes about a minute.
2. If Windows asks you to set up a PIN or Windows Hello, choose **Skip**. Scene 9 needs the password.
3. Your servers and the agent keep running in the `ataur` session in the background.
4. In Bilal's session, open **Edge** at `http://localhost:5173` and sign in as `admin`.
5. Snap Edge to the right half of the screen (Win + →) and File Explorer at `C:\AuditraCompany` to the left half.
6. Click once anywhere in the console so the browser allows alert sounds.

> Edge history for `localhost` is never collected. Only watched sites such as wetransfer.com and facebook.com are.

To read the agent window, switch back to `ataur` (Win + L > `ataur`). You rarely need to: the console shows everything.

---

## 3. Before the scenes: the current setup

These were entered through the admin API and are listed in **Admin > Audit Trail**.

- **Bilal Ahmed (E-1001):** Finance, Staff.
  - Can open data up to **MEDIUM** sensitivity, in the categories **FINANCIAL** and **CUSTOMER**.
  - Shift **09:00–02:00 every day**, for tonight's rehearsal only.
  - Windows account `MACBOOK\bilal`.
- **Data catalogue:**

| Folder / file | Category | Sensitivity | Bilal allowed? |
|---|---|---|---|
| `Finance` | Financial | MEDIUM | yes |
| `Payroll` | Financial | **HIGH** | no (too sensitive) |
| `HR` | HR / employee | HIGH | no |
| `HR\employees_cnic.csv` | National ID | HIGH | no |
| `Medical` | Health (special category) | HIGH | no |
| `Legal` | Criminal records | HIGH | no |
| `Customers` | Customer | MEDIUM | yes |
| `Biometrics` | Biometric (special category) | HIGH | no, and it is not in the RoPA |

- **Data subjects:** Ali Khan (`ali_khan_profile.csv`) and Fatima Noor (`fatima_noor_profile.csv`), both with consent **given**.
- **DPO:** designated and compliant.

---

## 4. Scenes

Do each scene as `bilal`, then look at the console. Wait about 15 seconds between scenes.

To open a `.csv` file, right-click it, choose **Open with**, then **Notepad**. Close Notepad afterwards.

### Part A: inside the shift

| # | Do this | Should it be caught? | What you should see |
|---|---|---|---|
| 1 | Open `Finance\invoices_2026.csv` | **No.** He is allowed. | **Activity** gains "Bilal Ahmed opened invoices_2026.csv". No incident, no sound. This proves there is no false positive. |
| 2 | Plug in the USB stick | **Indicator only** | Activity: "connected …USB…". **Incidents** gains a *USB storage connected during shift*, LOW, marked *Indicator*. No toast. |
| 3 | Open `Payroll\salaries_2026.csv` | **Yes** | Toast and sound. **Access beyond role scope**, Art. 25, HIGH, about 55. |
| 4 | Open `Medical\patient_records.csv` | **Yes** | **Special category data**, Art. 9 and 25, CRITICAL, about 75–90 |
| 5 | Open `Legal\criminal_record_checks.csv` | **Yes** | **Criminal offence data**, Art. 10, CRITICAL |
| 6 | Open `Biometrics\fingerprint_enrolment.csv` | **Yes** | Art. 9, 25 and **30** (not in the RoPA) |
| 7 | Open `Customers\fatima_noor_profile.csv` | **No.** Customer data is allowed and consent is given. | Activity row only |

After scene 6, Bilal has 3 or more violations in 7 days. Every new incident's score now includes **"Art. 83 escalation +10"**.

### Part B: consent and data-subject rights (the console changes, Bilal acts)

| # | Do this | Should it be caught? | What you should see |
|---|---|---|---|
| 8 | In the console go to **GDPR Records > Consent**, edit Ali Khan's record, and set **Status = Withdrawn**. Then, as Bilal, open `Customers\ali_khan_profile.csv`. | **Yes** | **Processing after consent was withdrawn**, Art. 7, CRITICAL |
| 9 | Still in the console, on **GDPR Records > Subject requests**, add an **Objection (Art. 21)** for Fatima Noor. Then open `fatima_noor_profile.csv` again. | **Yes** | **Objection to processing not respected**, Art. 21 |

### Part C: after the shift (the insider scenario)

10. In the console, open **Admin > Employees & Access**, edit Bilal, set **Shift ends** to the current time (for example 23:50), and save.

| # | Do this | Should it be caught? | What you should see |
|---|---|---|---|
| 11 | Unplug the USB stick and plug it back in | **Yes** | **USB storage connected outside shift**, Art. 32, HIGH |
| 12 | Copy `HR\employees_cnic.csv` to the USB stick (drag it in Explorer) | **Yes** | **Sensitive file copied to USB**, Art. 32, 5(1)(f), 87 and 25, CRITICAL, about 90–100. Open it to show the breakdown, the evidence (source path → USB path) and the AI score. |
| 13 | Copy `Payroll\salaries_2026.csv` and `Medical\patient_records.csv` to the USB stick as well | **Yes** | Each copy is its own incident, plus **Bulk export of personal records to USB** (Art. 5 and 32), because 3 files went out within 10 minutes |
| 14 | Delete `Customers\leads_1.csv`, `leads_2.csv` and `leads_3.csv` | **Yes** | **Deletion of sensitive files**, Art. 32 and 5(1)(f) |
| 15 | In Edge, open `https://wetransfer.com` and stay on the page for about 30 seconds | **Yes** | **Personal cloud / file-sharing site** as a potential violation (personal data was opened in the last 30 minutes). Edge can take up to a minute to save the visit. |
| 16 | Open `https://facebook.com` | **Policy indicator** | *Social media during work*, LOW, Policy (not GDPR) |
| 17 | Open `Customers\fatima_noor_profile.csv` in Notepad and press **Ctrl + P**, choose **Microsoft Print to PDF**, and save | **Indicator** | **Sensitive document printed**, Art. 32, LOW |

Then open **Employees > Bilal Ahmed**. The **AI anomaly score** for today should be high, with reasons such as "activity outside shift", "files copied to USB" and "USB connections". It is compared with a typical CERT employee-day.

### Part D: logons and Windows security (to do as `ataur`)

| # | Do this | Should it be caught? | What you should see |
|---|---|---|---|
| 18 | As Bilal press **Win + L**, type a **wrong** password **5 times**, then the right one | **Yes** | **Many failed logons, then a success**, Art. 32. A 6th wrong attempt would lock the account for 5 minutes and add an *Account locked out* indicator. |
| 19 | Switch to `ataur`. In the **administrator** PowerShell (not the agent window, open a second one) run `net user temp1 Temp@12345 /add` | **Yes** | **New user account created**, Art. 32 and 25, by `MACBOOK\ataur` (not linked to an employee) |
| 20 | `net localgroup administrators temp1 /add` | **Yes** | **User added to an administrators group**, Art. 25 and 32, HIGH |
| 21 | Clean up: `net user temp1 /delete` | No | — |

Optional, more drastic: `auditpol /set /subcategory:"File System" /success:enable` produces **Audit policy changed**, Art. 32 and 5(2). Do **not** clear the Security log on this laptop: that permanently deletes the history.

### Part E: GDPR records only (no laptop activity)

| # | Do this in the console | What you should see within 1 minute |
|---|---|---|
| 22 | **Subject requests:** add an **Access** request for Ali Khan with **Received** 40 days ago | **Data-subject request not fulfilled within 30 days**, Art. 15 |
| 23 | **Breaches:** add a breach with **Detected** 4 days ago, high risk, and nothing notified | **Breach not reported within 72 hours** (Art. 33) and **Data subjects not notified** (Art. 34) |
| 24 | **DPO:** untick "Acts independently" and save. Then, as Bilal, open any HIGH file. | **No DPO for high-risk processing**, Art. 37 |

Undo 24 afterwards by ticking the box again.

---

## 5. What to show on each incident (the "is the score right?" answer)

Open any incident from **Overview** or **Incidents**:

1. **What happened:** the sentence and the GDPR articles.
2. **Decision:** *Start investigation*, *Acknowledge*, *Escalate to DPO*, *Resolve* (needs a note) and *False positive* (needs a note). On a USB incident, *Report lost device* opens a breach record with the 72-hour Art. 33 clock (see **GDPR Records > Breaches**).
3. **How the score was built:** every point with its reason, for example rule CRITICAL +70, extra articles +10, AI +4, Art. 83 +10, giving 94.
4. **AI anomaly signal:** today's score and the features that stand out.
5. **Evidence:** Windows record, then the agent's structured event, then the catalogue match, then the rules that matched, then the score. Raw fields such as path, source path, process and device are shown in monospace.
6. **Timeline:** everything Bilal did 30 minutes before and after. Evidence rows are highlighted.

Every decision is written to **Admin > Audit Trail**. Marking incidents as false positives changes the **officer precision** figure on the Overview.

**Reports > Download PDF** shows all of this in one report. Each employee page has its own report.

---

## 6. Reset for another rehearsal

1. **Admin > Agents & Health > Reset activity**, then type `RESET`. This deletes events and incidents but keeps employees, the catalogue and the GDPR records.
2. Restore the deleted files and the folders: in an **administrator** PowerShell run
   `powershell -ExecutionPolicy Bypass -File E:\Auditra\scripts\windows\setup_demo_machine.ps1`. It only re-creates what is missing.
3. Set Ali Khan's consent back to **Given**, and delete Fatima's objection and the test requests and breaches if you added them.
4. Delete the files from the USB stick.

## 7. Presentation day (two laptops)

1. Set Bilal's shift back to **09:00–18:00, Mon–Fri**. Scene 2 is only an indicator if the presentation is inside that shift. If it isn't, use a shift that covers it.
2. Connect both laptops to the same phone hotspot. On this laptop run, once, in an administrator PowerShell:
   `powershell -ExecutionPolicy Bypass -File E:\Auditra\scripts\windows\setup_server_firewall.ps1`. It prints the address to use, for example `http://192.168.43.20:5173`.
3. On the officer laptop, open that address and sign in.
4. Set this laptop to never sleep while plugged in.

## If something does not appear

| Symptom | Check |
|---|---|
| Nothing appears at all | **Agents & Health**: is the laptop online, and is "events waiting to send" growing? Waiting events mean the server is unreachable; they are sent when it is back. Otherwise run `AuditraAgent.exe status` in an Administrator PowerShell: it shows the end of the agent log. Or run `AuditraAgent.exe stop`, then `AuditraAgent.exe run`, to see each `>` line. |
| File opens are not captured | **Agents & Health**: are the *Security log*, *Audit policy* and *File auditing* checks green? Is the file in a catalogue folder? Did you open it with Notepad, not just preview it in Explorer? Explorer previews are ignored on purpose. |
| USB copy not captured | The agent log shows `watching removable drive E:\` when the stick is plugged in. Copy a real file, not a shortcut. |
| Website not captured | Edge can take up to a minute to save history. Close the tab to force it. |
| Wrong person on an event | **Admin > Employees & Access > Accounts seen by agents but not linked**: link the account to the right employee. |
