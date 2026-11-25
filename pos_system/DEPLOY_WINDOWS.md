# Deploying the POS on Windows Server 2022

This guide sets up the POS on one Windows Server 2022 machine. Follow the parts in order. Every command is meant to be **copied and pasted into PowerShell opened as Administrator** unless it says otherwise.

## How it fits together

```
 Browsers (cashiers, admins)
        │  https://pos.yourcompany.com   (port 443)
        ▼
 ┌──────────────────────────── Windows Server 2022 ───────────────────────────┐
 │  IIS  ── handles HTTPS, serves product images (/media/)                     │
 │   │      forwards everything else to ↓                                      │
 │   ▼                                                                         │
 │  Waitress (Windows service "POS") on 127.0.0.1:8000  ── runs the Django app │
 │   │                                                                         │
 │   ▼                                                                         │
 │  PostgreSQL 17  ── databases: pos_system (live) and pos_archive (old sales) │
 │                                                                             │
 │  Task Scheduler ── hourly: archive old sales · nightly: backups             │
 └─────────────────────────────────────────────────────────────────────────────┘
```

> **Why not gunicorn?** The `Procfile` uses gunicorn, which only runs on Linux. On Windows the app runs with **Waitress** through `serve_windows.py`.

### Folder layout used in this guide

| Folder | What goes there |
|---|---|
| `C:\POS\app` | The application code (the folder that contains `manage.py`) |
| `C:\POS\venv` | Python virtual environment |
| `C:\POS\logs` | Service logs |
| `C:\POS\backups` | Database and image backups |
| `C:\POS\iis` | Tiny folder holding the IIS `web.config` |
| `C:\POS\tools` | NSSM (service helper) |

### What you need before you start

- [ ] Administrator access to the server
- [ ] A name for the site, for example `pos.yourcompany.com`, with a DNS record pointing at the server's IP (ask your network admin). Inside a LAN only, an internal DNS name is fine.
- [ ] An SSL certificate for that name (Part 7 explains the options)
- [ ] The code you tested. **Deploy the `main` branch** after `security/p0-fixes` has been merged into it.

---

## Part 1 — Prepare the server

1. Install Windows updates and restart.
2. Create the folders:

   ```powershell
   New-Item -ItemType Directory -Force C:\POS\app, C:\POS\logs, C:\POS\backups, C:\POS\iis, C:\POS\tools, C:\POS\secrets
   ```

3. Check the time zone. The app uses **Asia/Manila** time, so set the server to match and sales times line up with the clock on the wall:

   ```powershell
   Set-TimeZone -Id "Singapore Standard Time"   # UTC+8, same as Manila
   Get-TimeZone
   ```

---

## Part 2 — Install the software

### 2.1 Python 3.13

1. Download **Python 3.13 (64-bit Windows installer)** from <https://www.python.org/downloads/windows/>.
2. Run it and choose **Customize installation**:
   - Tick **Add python.exe to PATH**
   - On *Advanced Options* tick **Install Python 3.13 for all users** (so it goes into `C:\Program Files\Python313`, which the Windows service can reach)
3. Close and reopen PowerShell, then check:

   ```powershell
   python --version     # should print Python 3.13.x
   ```

### 2.2 PostgreSQL 17

1. Download the Windows installer from <https://www.postgresql.org/download/windows/> (EDB installer).
2. Run it with the defaults. When it asks:
   - **Password for the `postgres` superuser**: choose a strong one and **write it down somewhere safe**.
   - **Port**: keep `5432`.
   - Stack Builder at the end: untick it, you don't need it.
3. Check that the service is running:

   ```powershell
   Get-Service postgresql*
   ```

   Note the exact service name (for example `postgresql-x64-17`); you need it in Part 6.

### 2.3 Git (recommended, makes updates easy)

Download from <https://git-scm.com/download/win> and install with the defaults.
(If you prefer, you can copy the code over as a ZIP instead; see Part 4.)

### 2.4 NSSM (runs the app as a Windows service)

1. Download `nssm-2.24.zip` from <https://nssm.cc/download>.
2. Unzip it and copy `nssm-2.24\win64\nssm.exe` to `C:\POS\tools\nssm.exe`.

---

## Part 3 — Create the databases

1. Open the PostgreSQL command prompt (it asks for the `postgres` password from 2.2):

   ```powershell
   & "C:\Program Files\PostgreSQL\17\bin\psql.exe" -U postgres -h 127.0.0.1
   ```

2. Paste these lines. **Replace `CHANGE_ME_strong_password`** with a new password for the app.
   Use only **letters and numbers** (at least 20 of them). Symbols like `@ : / #` break the connection setting later.

   ```sql
   CREATE USER pos_user WITH PASSWORD 'CHANGE_ME_strong_password';
   CREATE DATABASE pos_system  OWNER pos_user;
   CREATE DATABASE pos_archive OWNER pos_user;
   \q
   ```

3. **Keep PostgreSQL private.** The app connects from the same machine, so port 5432 must not be open to the network. Remove any firewall rule the installer may have added:

   ```powershell
   Get-NetFirewallRule | Where-Object DisplayName -like "*Postgre*" | Remove-NetFirewallRule
   ```

---

## Part 4 — Put the application on the server

### Option A — with Git (recommended)

```powershell
cd C:\POS
git clone <your-repository-url> repo
```

The repository contains a `pos_system` folder holding `manage.py`. Make `C:\POS\app` point to it:

```powershell
Remove-Item C:\POS\app          # the empty folder made in Part 1
New-Item -ItemType Junction -Path C:\POS\app -Target C:\POS\repo\pos_system
Test-Path C:\POS\app\manage.py  # must print True
```

### Option B — copy the files

Copy the **contents** of your `pos_system` folder (the one with `manage.py`) into `C:\POS\app`. **Do not copy**:
`.env`, `db.sqlite3`, `pos_archive.sqlite3`, `.venv`, `staticfiles`, `__pycache__`, `.impeccable`, `tasks`.

### Create the Python environment and install packages

```powershell
python -m venv C:\POS\venv
C:\POS\venv\Scripts\python.exe -m pip install --upgrade pip
C:\POS\venv\Scripts\pip.exe install -r C:\POS\app\requirements.txt
C:\POS\venv\Scripts\pip.exe install waitress
```

---

## Part 5 — Configure the app (the `.env` file)

The app reads its settings from a file called `.env` next to `manage.py`.

1. Generate a secret key (copy the long line it prints):

   ```powershell
   C:\POS\venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

2. Create the file:

   ```powershell
   notepad C:\POS\app\.env
   ```

   Paste this in, replace the three placeholders, then save:

   ```ini
   # PRODUCTION settings. Never put DJANGO_DEBUG=1 in this file.
   DJANGO_SECRET_KEY=PASTE_THE_SECRET_KEY_HERE
   DJANGO_ALLOWED_HOSTS=pos.yourcompany.com
   DJANGO_CSRF_TRUSTED_ORIGINS=https://pos.yourcompany.com
   DATABASE_URL=postgres://pos_user:CHANGE_ME_strong_password@127.0.0.1:5432/pos_system

   # Tells browsers to always use HTTPS for 30 days. Set it to 0 while you are
   # still testing with a self-signed certificate (see Part 7).
   DJANGO_HSTS_SECONDS=2592000
   ```

   | Setting | What to put |
   |---|---|
   | `DJANGO_ALLOWED_HOSTS` | The name(s) people type in the browser, comma-separated, no `https://` |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | The same name(s) **with** `https://` in front |
   | `DATABASE_URL` | The `pos_user` password from Part 3 |

   The archive database (`pos_archive`) is found automatically on the same PostgreSQL server.

   > Notepad sometimes saves as `.env.txt`. Check with `Get-ChildItem C:\POS\app -Force -Filter .env*`. If you see `.env.txt`, rename it: `Rename-Item C:\POS\app\.env.txt .env`

3. Lock the file so only administrators and the service can read it:

   ```powershell
   icacls C:\POS\app\.env /inheritance:r /grant:r "Administrators:F" "SYSTEM:R"
   ```

---

## Part 6 — Prepare the database and test the app

Run these one at a time. Each one should finish without a red error.

```powershell
cd C:\POS\app
$py = "C:\POS\venv\Scripts\python.exe"

& $py manage.py check --deploy          # checks the production settings
& $py manage.py migrate --noinput       # creates the tables
& $py manage.py createcachetable        # needed by the sign-in lockout
& $py manage.py setup_archive_db        # prepares the pos_archive database
& $py manage.py collectstatic --noinput # gathers CSS/JS/fonts
```

`check --deploy` may print a few warnings; read them, but they don't stop you. A message starting with `ImproperlyConfigured` means the `.env` file is wrong (Part 5).

### Create the platform administrator

This is the all-stores administrator who signs in at `/platform/` and creates the stores and their users.

```powershell
& $py manage.py createsuperuser
```

Pick a username and a strong password (at least 8 characters, not common, not all numbers).

### Quick test

```powershell
& $py serve_windows.py
```

Leave it running and open a **second** PowerShell window:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/accounts/login/ -Headers @{ Host = "pos.yourcompany.com"; "X-Forwarded-Proto" = "https" } -UseBasicParsing | Select-Object StatusCode
```

`200` means the app works. Go back to the first window and press **Ctrl+C** to stop it.

### Make it a Windows service (starts automatically with the server)

Replace `postgresql-x64-17` if your service name from 2.2 is different.

```powershell
$nssm = "C:\POS\tools\nssm.exe"
& $nssm install POS "C:\POS\venv\Scripts\python.exe" "C:\POS\app\serve_windows.py"
& $nssm set POS AppDirectory    "C:\POS\app"
& $nssm set POS DisplayName     "POS System (Waitress)"
& $nssm set POS Start           SERVICE_AUTO_START
& $nssm set POS DependOnService postgresql-x64-17
& $nssm set POS AppStdout       "C:\POS\logs\pos.log"
& $nssm set POS AppStderr       "C:\POS\logs\pos.log"
& $nssm set POS AppRotateFiles  1
& $nssm set POS AppRotateOnline 1
& $nssm set POS AppRotateBytes  10485760
& $nssm set POS AppExit Default Restart
Start-Service POS
Get-Service POS        # Status should be Running
```

If it shows `Paused` or `Stopped`, look at the log: `Get-Content C:\POS\logs\pos.log -Tail 40`.

---

## Part 7 — IIS (HTTPS in front of the app)

### 7.1 Install IIS and two add-ons

```powershell
Install-WindowsFeature Web-Server, Web-Static-Content, Web-Http-Redirect -IncludeManagementTools
```

Then download and install both of these (run each installer with the defaults):

1. **URL Rewrite 2.1**: <https://www.iis.net/downloads/microsoft/url-rewrite>
2. **Application Request Routing (ARR) 3.0**: <https://www.iis.net/downloads/microsoft/application-request-routing>

### 7.2 Turn on forwarding

```powershell
$appcmd = "$env:windir\system32\inetsrv\appcmd.exe"

# Turn ARR's proxy on, and pass the real site name (Host header) through to the app.
& $appcmd set config -section:system.webServer/proxy /enabled:"True" /preserveHostHeader:"True" /timeout:"00:02:00" /commit:apphost

# Allow IIS to tell the app "the browser used HTTPS".
& $appcmd set config -section:system.webServer/rewrite/allowedServerVariables /+"[name='HTTP_X_FORWARDED_PROTO']" /commit:apphost
```

> **Don't skip `preserveHostHeader`.** Without it every page returns **400 Bad Request**.

### 7.3 Get a certificate

Pick **one**:

- **The site is reachable from the internet** (public DNS, ports 80/443 forwarded): use **win-acme**, a free Let's Encrypt tool that also renews the certificate automatically. Download from <https://www.win-acme.com/>, run `wacs.exe` *after* finishing 7.4, choose *"Create certificate (default settings)"*, then pick the `POS` site.
- **Your company has its own certificate** (a `.pfx` file): import it with
  `Import-PfxCertificate -FilePath C:\path\to\cert.pfx -CertStoreLocation Cert:\LocalMachine\My -Password (Read-Host -AsSecureString "PFX password")`
- **LAN only and no company certificate, for testing only**: a self-signed certificate. Browsers will show a warning until you install it as trusted on each PC. Set `DJANGO_HSTS_SECONDS=0` in `.env` (then `Restart-Service POS`) while you use it.
  ```powershell
  New-SelfSignedCertificate -DnsName "pos.yourcompany.com" -CertStoreLocation Cert:\LocalMachine\My -NotAfter (Get-Date).AddYears(2)
  ```

### 7.4 Create the IIS site

1. Remove the sample site so it doesn't take port 80:

   ```powershell
   Import-Module WebAdministration
   Remove-Website -Name "Default Web Site" -ErrorAction SilentlyContinue
   ```

2. Create `C:\POS\iis\web.config`:

   ```powershell
   notepad C:\POS\iis\web.config
   ```

   Paste this in and save:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <configuration>
     <system.webServer>
       <rewrite>
         <rules>
           <!-- 1. Send http:// visitors to https:// -->
           <rule name="HTTP to HTTPS" stopProcessing="true">
             <match url="(.*)" />
             <conditions>
               <add input="{HTTPS}" pattern="off" />
               <add input="{REQUEST_URI}" pattern="^/\.well-known/" negate="true" />
             </conditions>
             <action type="Redirect" url="https://{HTTP_HOST}/{R:1}" redirectType="Permanent" />
           </rule>
           <!-- 2. Forward everything (except product images) to the app -->
           <rule name="Forward to POS" stopProcessing="true">
             <match url="(.*)" />
             <conditions>
               <add input="{REQUEST_URI}" pattern="^/media/" negate="true" />
               <add input="{REQUEST_URI}" pattern="^/\.well-known/" negate="true" />
             </conditions>
             <serverVariables>
               <set name="HTTP_X_FORWARDED_PROTO" value="https" />
             </serverVariables>
             <action type="Rewrite" url="http://127.0.0.1:8000/{R:1}" />
           </rule>
         </rules>
       </rewrite>
       <security>
         <requestFiltering>
           <!-- allow uploads up to 20 MB -->
           <requestLimits maxAllowedContentLength="20971520" />
         </requestFiltering>
       </security>
     </system.webServer>
   </configuration>
   ```

3. Create the site, the HTTPS binding, and the `/media` folder for product images:

   ```powershell
   $hostName = "pos.yourcompany.com"      # ← your site name

   New-Item -ItemType Directory -Force C:\POS\app\media | Out-Null
   New-Website -Name "POS" -PhysicalPath "C:\POS\iis" -Port 80 -HostHeader $hostName
   New-WebBinding -Name "POS" -Protocol https -Port 443 -HostHeader $hostName -SslFlags 1
   New-WebVirtualDirectory -Site "POS" -Name "media" -PhysicalPath "C:\POS\app\media"

   # IIS may read the images; nothing else.
   icacls C:\POS\app\media /grant "IIS_IUSRS:(OI)(CI)R" "IUSR:(OI)(CI)R"
   ```

4. Attach the certificate (skip if you use win-acme; it does this for you):

   ```powershell
   $cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Subject -like "*$hostName*" } | Sort-Object NotAfter -Descending | Select-Object -First 1
   (Get-WebBinding -Name "POS" -Protocol https).AddSslCertificate($cert.Thumbprint, "My")
   ```

### 7.5 Open the firewall (web ports only)

```powershell
New-NetFirewallRule -DisplayName "POS HTTP"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "POS HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

**Do not** open port 8000 (Waitress) or 5432 (PostgreSQL).

### 7.6 Try it

From another PC, open **https://pos.yourcompany.com/platform/** and sign in with the administrator from Part 6. Then:

- [ ] Create a store and a store user
- [ ] Sign in at **https://pos.yourcompany.com/** as that store user
- [ ] Add a product **with an image** and check that the image shows
- [ ] Make a test sale and print/view the receipt
- [ ] Open **http://**pos.yourcompany.com and check that it jumps to **https://**

---

## Part 8 — Scheduled jobs

### 8.1 Hourly sales archiving

Each store's archive time and retention period are set in the app; this task only checks every hour which stores are due.

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\POS\venv\Scripts\python.exe" -Argument "manage.py archive_sales" -WorkingDirectory "C:\POS\app"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "POS - Archive sales" -Action $action -Trigger $trigger -User "SYSTEM" -RunLevel Highest
```

### 8.2 Nightly backups

1. Store the database password for the backup tool (replace the password):

   ```powershell
   Set-Content -Path C:\POS\secrets\pgpass.conf -Value "127.0.0.1:5432:*:pos_user:CHANGE_ME_strong_password" -Encoding ascii
   icacls C:\POS\secrets /inheritance:r /grant:r "Administrators:F" "SYSTEM:F"
   ```

2. Create the backup script:

   ```powershell
   notepad C:\POS\tools\backup.ps1
   ```

   ```powershell
   # Backs up both databases and product images. Keeps 14 days.
   $ErrorActionPreference = "Stop"
   $env:PGPASSFILE = "C:\POS\secrets\pgpass.conf"
   $pgDump = "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe"
   $dest   = "C:\POS\backups"
   $stamp  = Get-Date -Format "yyyy-MM-dd_HHmm"

   foreach ($db in "pos_system", "pos_archive") {
       & $pgDump -h 127.0.0.1 -U pos_user -F c -f "$dest\${db}_$stamp.dump" $db
       if ($LASTEXITCODE -ne 0) { throw "pg_dump failed for $db" }
   }
   if (Get-ChildItem C:\POS\app\media -Recurse -File) {
       Compress-Archive -Path C:\POS\app\media\* -DestinationPath "$dest\media_$stamp.zip"
   }
   Get-ChildItem $dest -File | Where-Object LastWriteTime -lt (Get-Date).AddDays(-14) | Remove-Item
   ```

3. Schedule it for 2:00 AM every night:

   ```powershell
   $action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\POS\tools\backup.ps1"
   $trigger = New-ScheduledTaskTrigger -Daily -At 2am
   Register-ScheduledTask -TaskName "POS - Nightly backup" -Action $action -Trigger $trigger -User "SYSTEM" -RunLevel Highest
   ```

4. Run it once now and check that files appear:

   ```powershell
   Start-ScheduledTask -TaskName "POS - Nightly backup"
   Get-ChildItem C:\POS\backups
   ```

> **Copy backups off the server.** A backup on the same disk won't help if that disk fails. Copy `C:\POS\backups` to a NAS, another server, or cloud storage regularly.

### Restoring a backup (keep these steps somewhere safe)

```powershell
Stop-Service POS
$env:PGPASSFILE = "C:\POS\secrets\pgpass.conf"
& "C:\Program Files\PostgreSQL\17\bin\pg_restore.exe" -h 127.0.0.1 -U pos_user -d pos_system --clean --if-exists "C:\POS\backups\pos_system_YYYY-MM-DD_HHMM.dump"
& "C:\Program Files\PostgreSQL\17\bin\pg_restore.exe" -h 127.0.0.1 -U pos_user -d pos_archive --clean --if-exists "C:\POS\backups\pos_archive_YYYY-MM-DD_HHMM.dump"
Start-Service POS
```

Practise a restore once on a test machine so you know it works before you need it.

---

## Part 9 — Moving existing data (optional)

If your current PostgreSQL already has real stores, products and sales, move them instead of starting empty. **On the old machine:**

```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -h 127.0.0.1 -U <old_user> -F c -f pos_system.dump <old_database_name>
```

Copy `pos_system.dump` and the old `media` folder to the server. **On the server**, before Part 6 (or after `Stop-Service POS`):

```powershell
$env:PGPASSFILE = "C:\POS\secrets\pgpass.conf"
& "C:\Program Files\PostgreSQL\17\bin\pg_restore.exe" -h 127.0.0.1 -U pos_user -d pos_system --no-owner --clean --if-exists C:\path\to\pos_system.dump
Copy-Item -Recurse C:\path\to\media\* C:\POS\app\media\
```

Then run the Part 6 commands (`migrate` etc.). They're safe to run on existing data. Do the same for `pos_archive` if the old system has archived sales.

---

## Part 10 — Installing a new version later

```powershell
Stop-Service POS
Start-ScheduledTask -TaskName "POS - Nightly backup"      # backup first
# wait until it finishes:  Get-ScheduledTaskInfo "POS - Nightly backup"

cd C:\POS\repo
git pull                                                  # (or copy the new files, Part 4 option B)

cd C:\POS\app
$py = "C:\POS\venv\Scripts\python.exe"
& "C:\POS\venv\Scripts\pip.exe" install -r requirements.txt
& $py manage.py migrate --noinput
& $py manage.py setup_archive_db
& $py manage.py collectstatic --noinput
Start-Service POS
```

Then open the site and do a quick test sale. Do updates outside store hours.

---

## Troubleshooting

| What you see | Likely cause | Fix |
|---|---|---|
| **400 Bad Request** on every page | Site name missing from `DJANGO_ALLOWED_HOSTS`, or IIS isn't passing the host name | Check `.env`; re-run the `preserveHostHeader` command in 7.2; `Restart-Service POS` |
| **403 Forbidden – CSRF verification failed** when signing in | `DJANGO_CSRF_TRUSTED_ORIGINS` wrong (needs `https://`) | Fix `.env`, `Restart-Service POS` |
| Browser says **"too many redirects"** | IIS isn't sending `X-Forwarded-Proto` | Re-run the `allowedServerVariables` command in 7.2; check the `serverVariables` block in `web.config` |
| **502.3 Bad Gateway** | The POS service isn't running | `Get-Service POS`; read `C:\POS\logs\pos.log` |
| Service won't start | Usually a `.env` mistake or wrong DB password | `Get-Content C:\POS\logs\pos.log -Tail 40` |
| Pages load but have **no styling** | `collectstatic` wasn't run | Run it (Part 6), `Restart-Service POS` |
| **Product images** don't show | `/media` virtual directory or permissions | Repeat step 3 of 7.4 |
| Can't sign in: "locked" | 5 wrong passwords lock the username for 15 minutes | Wait 15 minutes |
| Sales times look wrong | Server clock or time zone | Part 1 step 3 |

**Useful commands**

```powershell
Get-Service POS                                   # is it running?
Restart-Service POS                               # after changing .env
Get-Content C:\POS\logs\pos.log -Tail 50 -Wait    # watch the log live (Ctrl+C to stop)
Get-ScheduledTaskInfo "POS - Archive sales"       # last run result (0 = OK)
```

---

## Final checklist

- [ ] `.env` has **no** `DJANGO_DEBUG` line and is locked with `icacls`
- [ ] `manage.py check --deploy` ran
- [ ] The `POS` service is **Running** and set to start automatically
- [ ] The site opens over **https://** from another PC; http:// redirects
- [ ] Ports 8000 and 5432 are **not** open in the firewall
- [ ] Product image upload works
- [ ] Archive task and backup task are scheduled; a backup file exists
- [ ] Backups are copied off the server
- [ ] The `postgres` password, `pos_user` password and platform admin login are stored in a password manager
- [ ] Server restarted once, and the POS came back up on its own
