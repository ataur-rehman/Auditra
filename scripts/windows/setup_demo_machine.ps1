<#
Prepares the monitored (employee) laptop. Run once, in PowerShell opened with "Run as administrator":

    powershell -ExecutionPolicy Bypass -File scripts\windows\setup_demo_machine.ps1

What it changes (undo with undo_demo_machine.ps1):
  * saves the current audit policy to C:\AuditraCompany\.auditra\auditpol_backup.csv, then turns on
    the audit subcategories the agent reads (logons, file access, account and policy changes)
  * creates the company share C:\AuditraCompany with one folder per data category
  * adds an audit rule (SACL) to that folder so opening, changing or deleting a file is logged (4663)
  * enables the PrintService operational log (event 307)
  * sets an account lockout policy of 6 failed attempts for 5 minutes (event 4740), one more than the brute-force rule needs
  * enlarges the Security log to 256 MB so demo events are not overwritten
  * creates the local standard account "bilal" (you type the password)
#>
$ErrorActionPreference = 'Stop'

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Run this script from a PowerShell window opened with "Run as administrator".' -ForegroundColor Red
    exit 1
}

$Root = 'C:\AuditraCompany'
$StateDir = Join-Path $Root '.auditra'
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
(Get-Item $StateDir).Attributes = 'Hidden'

Write-Host '1/7  Saving current audit policy' -ForegroundColor Cyan
$backup = Join-Path $StateDir 'auditpol_backup.csv'
if (-not (Test-Path $backup)) {
    auditpol /backup /file:$backup | Out-Null
}
$lockoutBackup = Join-Path $StateDir 'lockout_backup.txt'
if (-not (Test-Path $lockoutBackup)) {
    net accounts | Out-File -FilePath $lockoutBackup -Encoding utf8
}

Write-Host '2/7  Enabling audit subcategories' -ForegroundColor Cyan
# GUIDs are language independent.
$subcategories = @{
    'Logon'                           = '{0CCE9215-69AE-11D9-BED3-505054503030}'
    'Other Logon/Logoff Events'       = '{0CCE921C-69AE-11D9-BED3-505054503030}'
    'Account Lockout'                 = '{0CCE9217-69AE-11D9-BED3-505054503030}'
    'File System'                     = '{0CCE921D-69AE-11D9-BED3-505054503030}'
    'Other Object Access Events'      = '{0CCE9227-69AE-11D9-BED3-505054503030}'
    'User Account Management'         = '{0CCE9235-69AE-11D9-BED3-505054503030}'
    'Security Group Management'       = '{0CCE9237-69AE-11D9-BED3-505054503030}'
    'Audit Policy Change'             = '{0CCE922F-69AE-11D9-BED3-505054503030}'
}
foreach ($name in $subcategories.Keys) {
    auditpol /set /subcategory:$($subcategories[$name]) /success:enable /failure:enable | Out-Null
    Write-Host "     $name"
}

Write-Host '3/7  Creating the company share' -ForegroundColor Cyan
$folders = @('Finance', 'Payroll', 'HR', 'Medical', 'Legal', 'Customers', 'Biometrics')
foreach ($folder in $folders) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $folder) | Out-Null
}
$files = @{
    'Finance\invoices_2026.csv'           = "invoice_no,client,amount_pkr,due_date`nINV-1041,Crescent Textiles,482000,2026-11-05`nINV-1042,Nova Foods,129500,2026-11-12`n"
    'Finance\budget_q4.csv'               = "department,budget_pkr,spent_pkr`nFinance,2500000,1840000`nHR,1200000,910000`n"
    'Payroll\salaries_2026.csv'           = "employee_code,name,grade,monthly_salary_pkr,bank_account`nE-1001,Bilal Ahmed,G7,185000,PK36SCBL0000001123456702`nE-1002,Sara Khan,G9,265000,PK36SCBL0000001123456703`n"
    'HR\employees_cnic.csv'               = "employee_code,name,cnic,date_of_birth`nE-1001,Bilal Ahmed,35202-1234567-1,1996-04-12`nE-1002,Sara Khan,35201-7654321-2,1993-09-30`n"
    'HR\performance_reviews.csv'          = "employee_code,year,rating,notes`nE-1001,2025,3,Meets expectations`nE-1002,2025,4,Exceeds expectations`n"
    'Medical\patient_records.csv'         = "patient_id,name,diagnosis,medication`nP-201,Usman Tariq,Type 2 diabetes,Metformin`nP-202,Hina Raza,Asthma,Salbutamol`n"
    'Legal\criminal_record_checks.csv'    = "candidate,cnic,check_date,result`nKamran Ali,35202-1111111-1,2026-09-14,Conviction 2019 (theft)`n"
    'Customers\leads_1.csv'               = "lead_id,name,phone`nL-1,Ahmed Raza,0301-1112223`n"
    'Customers\leads_2.csv'               = "lead_id,name,phone`nL-2,Nida Aslam,0302-2223334`n"
    'Customers\leads_3.csv'               = "lead_id,name,phone`nL-3,Omar Farooq,0303-3334445`n"
    'Customers\ali_khan_profile.csv'      ="customer_id,name,phone,email,address`nC-501,Ali Khan,0300-1234567,ali.khan@example.com,House 12 Street 4 Lahore`n"
    'Customers\fatima_noor_profile.csv'   = "customer_id,name,phone,email,address`nC-502,Fatima Noor,0321-7654321,fatima.noor@example.com,Flat 3 Block B Karachi`n"
    'Biometrics\fingerprint_enrolment.csv'= "employee_code,template_hash,enrolled_at`nE-1001,9f2c...a71b,2026-01-10`n"
}
foreach ($relative in $files.Keys) {
    $path = Join-Path $Root $relative
    if (-not (Test-Path $path)) {
        Set-Content -Path $path -Value $files[$relative] -Encoding utf8 -NoNewline
    }
}

Write-Host '4/7  Adding the file-access audit rule (SACL)' -ForegroundColor Cyan
$acl = Get-Acl -Path $Root -Audit
$rights = [System.Security.AccessControl.FileSystemRights]'ReadData, WriteData, AppendData, Delete'
$inherit = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
$propagate = [System.Security.AccessControl.PropagationFlags]::None
$auditRule = New-Object System.Security.AccessControl.FileSystemAuditRule('Everyone', $rights, $inherit, $propagate, 'Success')
$acl.AddAuditRule($auditRule)
Set-Acl -Path $Root -AclObject $acl

Write-Host '5/7  Enabling the print log' -ForegroundColor Cyan
wevtutil sl Microsoft-Windows-PrintService/Operational /e:true

Write-Host '6/7  Lockout policy and Security log size' -ForegroundColor Cyan
net accounts /lockoutthreshold:6 /lockoutduration:5 /lockoutwindow:5 | Out-Null
wevtutil sl Security /ms:268435456

Write-Host '7/7  Local employee account "bilal"' -ForegroundColor Cyan
if (-not (Get-LocalUser -Name 'bilal' -ErrorAction SilentlyContinue)) {
    $password = Read-Host -AsSecureString 'Choose a password for the local account bilal'
    New-LocalUser -Name 'bilal' -Password $password -FullName 'Bilal Ahmed' -Description 'Auditra monitored employee' | Out-Null
    Add-LocalGroupMember -Group 'Users' -Member 'bilal'
    Write-Host '     created'
} else {
    Write-Host '     already exists'
}

Write-Host ''
Write-Host 'Done. Switch user to "bilal" once so Windows creates the profile, then install the agent:' -ForegroundColor Green
Write-Host '    double-click AuditraAgent.exe and type the enrolment code from the console'
Write-Host '    (or, for a rehearsal: cd E:\Auditra\agent; python -m auditra_agent run)'
