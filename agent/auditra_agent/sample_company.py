r"""The test company folder, C:\AuditraCompany: one folder per data category with a few realistic files.

It is what the data catalogue in a fresh Auditra points at, so opening, copying, printing or deleting these files
produces real Windows events and real incidents. These are the same files scripts/windows/setup_demo_machine.ps1
creates.

    AuditraAgent.exe test-folder                create it, keeping files that already exist (as Administrator)
    python -m auditra_agent test-folder-zip X   write the same folder as a zip (the console offers it for download)
"""
import zipfile
from pathlib import Path

ROOT = Path(r'C:\AuditraCompany')
FOLDERS = ['Finance', 'Payroll', 'HR', 'Medical', 'Legal', 'Customers', 'Biometrics']
FILES = {'Finance\\invoices_2026.csv': 'invoice_no,client,amount_pkr,due_date\n'
                               'INV-1041,Crescent Textiles,482000,2026-11-05\n'
                               'INV-1042,Nova Foods,129500,2026-11-12\n',
 'Finance\\budget_q4.csv': 'department,budget_pkr,spent_pkr\nFinance,2500000,1840000\nHR,1200000,910000\n',
 'Payroll\\salaries_2026.csv': 'employee_code,name,grade,monthly_salary_pkr,bank_account\n'
                               'E-1001,Bilal Ahmed,G7,185000,PK36SCBL0000001123456702\n'
                               'E-1002,Sara Khan,G9,265000,PK36SCBL0000001123456703\n',
 'HR\\employees_cnic.csv': 'employee_code,name,cnic,date_of_birth\n'
                           'E-1001,Bilal Ahmed,35202-1234567-1,1996-04-12\n'
                           'E-1002,Sara Khan,35201-7654321-2,1993-09-30\n',
 'HR\\performance_reviews.csv': 'employee_code,year,rating,notes\n'
                                'E-1001,2025,3,Meets expectations\n'
                                'E-1002,2025,4,Exceeds expectations\n',
 'Medical\\patient_records.csv': 'patient_id,name,diagnosis,medication\n'
                                 'P-201,Usman Tariq,Type 2 diabetes,Metformin\n'
                                 'P-202,Hina Raza,Asthma,Salbutamol\n',
 'Legal\\criminal_record_checks.csv': 'candidate,cnic,check_date,result\n'
                                      'Kamran Ali,35202-1111111-1,2026-09-14,Conviction 2019 (theft)\n',
 'Customers\\leads_1.csv': 'lead_id,name,phone\nL-1,Ahmed Raza,0301-1112223\n',
 'Customers\\leads_2.csv': 'lead_id,name,phone\nL-2,Nida Aslam,0302-2223334\n',
 'Customers\\leads_3.csv': 'lead_id,name,phone\nL-3,Omar Farooq,0303-3334445\n',
 'Customers\\ali_khan_profile.csv': 'customer_id,name,phone,email,address\n'
                                    'C-501,Ali Khan,0300-1234567,ali.khan@example.com,House 12 Street 4 Lahore\n',
 'Customers\\fatima_noor_profile.csv': 'customer_id,name,phone,email,address\n'
                                       'C-502,Fatima Noor,0321-7654321,fatima.noor@example.com,Flat 3 Block B '
                                       'Karachi\n',
 'Biometrics\\fingerprint_enrolment.csv': 'employee_code,template_hash,enrolled_at\nE-1001,9f2c...a71b,2026-01-10\n'}


def create(root=ROOT):
    """Create missing folders and files. Existing files are left as they are. Returns the files written."""
    root = Path(root)
    written = []
    for folder in FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    for relative, content in FILES.items():
        path = root / relative
        if not path.exists():
            path.write_text(content, encoding='utf-8', newline='\r\n')
            written.append(str(path))
    return written


def write_zip(target):
    """The folder as a zip whose top level is AuditraCompany/, to extract into C:\\ ."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for folder in FOLDERS:
            archive.writestr(f'AuditraCompany/{folder}/', '')
        for relative, content in FILES.items():
            archive.writestr('AuditraCompany/' + relative.replace('\\', '/'), content.replace('\n', '\r\n'))
    return target
