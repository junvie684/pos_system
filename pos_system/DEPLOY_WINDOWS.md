# Deploy the POS on Windows Server 2022 (quick guide)

Run everything in **PowerShell as Administrator**, top to bottom.
Stack: **IIS** (HTTPS + `/media`) → **Waitress** service on `127.0.0.1:8000` → **PostgreSQL 17**.
Deploy the `main` branch.

## 0. Set your values (re-run this block in each new PowerShell window)

```powershell
$HostName = "pos.yourcompany.com"          # site name (DNS must point to this server)
$DbPass   = "ChangeMeLettersAndNumbers123" # pos_user password: letters/numbers only, 20+ chars
$py       = "C:\POS\venv\Scripts\python.exe"
$pgBin    = "C:\Program Files\PostgreSQL\17\bin"
```

## 1. Install software

Install with defaults unless noted:

| Software | Notes |
|---|---|
| [Python 3.13 x64](https://www.python.org/downloads/windows/) | Customize → tick **Add to PATH** and **Install for all users** |
| [PostgreSQL 17](https://www.postgresql.org/download/windows/) | Save the `postgres` password; port 5432; skip Stack Builder |
| [Git](https://git-scm.com/download/win) | |
| [NSSM 2.24](https://nssm.cc/download) | Copy `win64\nssm.exe` to `C:\POS\tools\nssm.exe` |
| [URL Rewrite 2.1](https://www.iis.net/downloads/microsoft/url-rewrite) + [ARR 3.0](https://www.iis.net/downloads/microsoft/application-request-routing) | Install **after** step 2 (needs IIS) |

## 2. Prepare the server

```powershell
New-Item -ItemType Directory -Force C:\POS\logs, C:\POS\backups, C:\POS\iis, C:\POS\tools, C:\POS\secrets | Out-Null
Set-TimeZone -Id "Singapore Standard Time"   # UTC+8 = Manila
Install-WindowsFeature Web-Server, Web-Static-Content, Web-Http-Redirect -IncludeManagementTools
```

Now install URL Rewrite and ARR (table above).

## 3. Database

```powershell
& "$pgBin\psql.exe" -U postgres -h 127.0.0.1 -c "CREATE USER pos_user WITH PASSWORD '$DbPass';"
& "$pgBin\psql.exe" -U postgres -h 127.0.0.1 -c "CREATE DATABASE pos_system OWNER pos_user;"
& "$pgBin\psql.exe" -U postgres -h 127.0.0.1 -c "CREATE DATABASE pos_archive OWNER pos_user;"
Get-NetFirewallRule | Where-Object DisplayName -like "*Postgre*" | Remove-NetFirewallRule   # keep 5432 private
```

## 4. Code + Python packages

```powershell
git clone <your-repository-url> C:\POS\repo
New-Item -ItemType Junction -Path C:\POS\app -Target C:\POS\repo\pos_system
python -m venv C:\POS\venv
& $py -m pip install --upgrade pip
& $py -m pip install -r C:\POS\app\requirements.txt waitress
```

## 5. `.env` file

```powershell
$secret = & $py -c "import secrets; print(secrets.token_urlsafe(50))"
@"
DJANGO_SECRET_KEY=$secret
DJANGO_ALLOWED_HOSTS=$HostName
DJANGO_CSRF_TRUSTED_ORIGINS=https://$HostName
DATABASE_URL=postgres://pos_user:$DbPass@127.0.0.1:5432/pos_system
DJANGO_HSTS_SECONDS=2592000
"@ | Set-Content C:\POS\app\.env -Encoding ascii
icacls C:\POS\app\.env /inheritance:r /grant:r "Administrators:F" "SYSTEM:R"
```

> Never add `DJANGO_DEBUG=1`. Using a self-signed certificate for testing? Set `DJANGO_HSTS_SECONDS=0`.

## 6. Initialise the app

```powershell
cd C:\POS\app
& $py manage.py check --deploy
& $py manage.py migrate --noinput
& $py manage.py createcachetable
& $py manage.py setup_archive_db
& $py manage.py collectstatic --noinput
& $py manage.py createsuperuser          # platform admin (signs in at /platform/)
```

## 7. Windows service

Check the PostgreSQL service name with `Get-Service postgresql*` and change it below if it differs.

```powershell
$nssm = "C:\POS\tools\nssm.exe"
& $nssm install POS $py "C:\POS\app\serve_windows.py"
& $nssm set POS AppDirectory    C:\POS\app
& $nssm set POS Start           SERVICE_AUTO_START
& $nssm set POS DependOnService postgresql-x64-17
& $nssm set POS AppStdout       C:\POS\logs\pos.log
& $nssm set POS AppStderr       C:\POS\logs\pos.log
& $nssm set POS AppRotateFiles  1
& $nssm set POS AppRotateBytes  10485760
& $nssm set POS AppExit Default Restart
Start-Service POS; Get-Service POS       # should be Running
```

## 8. IIS site + HTTPS

```powershell
$appcmd = "$env:windir\system32\inetsrv\appcmd.exe"
& $appcmd set config -section:system.webServer/proxy /enabled:"True" /preserveHostHeader:"True" /timeout:"00:02:00" /commit:apphost
& $appcmd set config -section:system.webServer/rewrite/allowedServerVariables /+"[name='HTTP_X_FORWARDED_PROTO']" /commit:apphost

@'
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="HTTP to HTTPS" stopProcessing="true">
          <match url="(.*)" />
          <conditions>
            <add input="{HTTPS}" pattern="off" />
            <add input="{REQUEST_URI}" pattern="^/\.well-known/" negate="true" />
          </conditions>
          <action type="Redirect" url="https://{HTTP_HOST}/{R:1}" redirectType="Permanent" />
        </rule>
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
        <requestLimits maxAllowedContentLength="20971520" />
      </requestFiltering>
    </security>
  </system.webServer>
</configuration>
'@ | Set-Content C:\POS\iis\web.config -Encoding utf8

Import-Module WebAdministration
Remove-Website "Default Web Site" -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force C:\POS\app\media | Out-Null
New-Website -Name POS -PhysicalPath C:\POS\iis -Port 80 -HostHeader $HostName
New-WebBinding -Name POS -Protocol https -Port 443 -HostHeader $HostName -SslFlags 1
New-WebVirtualDirectory -Site POS -Name media -PhysicalPath C:\POS\app\media
icacls C:\POS\app\media /grant "IIS_IUSRS:(OI)(CI)R" "IUSR:(OI)(CI)R"

New-NetFirewallRule -DisplayName "POS HTTP"  -Direction Inbound -Protocol TCP -LocalPort 80  -Action Allow
New-NetFirewallRule -DisplayName "POS HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

**Certificate — pick one:**

- **Public site:** run [win-acme](https://www.win-acme.com/) `wacs.exe` → *Create certificate (default settings)* → site `POS`. It binds and auto-renews. Done.
- **Company `.pfx`:** `Import-PfxCertificate -FilePath C:\path\cert.pfx -CertStoreLocation Cert:\LocalMachine\My -Password (Read-Host -AsSecureString)`
- **LAN test only:** `New-SelfSignedCertificate -DnsName $HostName -CertStoreLocation Cert:\LocalMachine\My -NotAfter (Get-Date).AddYears(2)`

For `.pfx` or self-signed, bind it:

```powershell
$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object Subject -like "*$HostName*" | Sort-Object NotAfter -Descending | Select-Object -First 1
(Get-WebBinding -Name POS -Protocol https).AddSslCertificate($cert.Thumbprint, "My")
```

## 9. Scheduled jobs (archiving + backups)

```powershell
# Hourly archiving
$a = New-ScheduledTaskAction -Execute $py -Argument "manage.py archive_sales" -WorkingDirectory C:\POS\app
$t = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "POS - Archive sales" -Action $a -Trigger $t -User SYSTEM -RunLevel Highest

# Backup credentials
Set-Content C:\POS\secrets\pgpass.conf "127.0.0.1:5432:*:pos_user:$DbPass" -Encoding ascii
icacls C:\POS\secrets /inheritance:r /grant:r "Administrators:F" "SYSTEM:F"

# Backup script (both DBs + images, keeps 14 days)
@'
$ErrorActionPreference = "Stop"
$env:PGPASSFILE = "C:\POS\secrets\pgpass.conf"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
foreach ($db in "pos_system", "pos_archive") {
    & "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -h 127.0.0.1 -U pos_user -F c -f "C:\POS\backups\${db}_$stamp.dump" $db
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed for $db" }
}
if (Get-ChildItem C:\POS\app\media -Recurse -File) {
    Compress-Archive -Path C:\POS\app\media\* -DestinationPath "C:\POS\backups\media_$stamp.zip"
}
Get-ChildItem C:\POS\backups -File | Where-Object LastWriteTime -lt (Get-Date).AddDays(-14) | Remove-Item
'@ | Set-Content C:\POS\tools\backup.ps1 -Encoding utf8

# Nightly at 2 AM
$a = New-ScheduledTaskAction -Execute powershell.exe -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\POS\tools\backup.ps1"
$t = New-ScheduledTaskTrigger -Daily -At 2am
Register-ScheduledTask -TaskName "POS - Nightly backup" -Action $a -Trigger $t -User SYSTEM -RunLevel Highest
Start-ScheduledTask "POS - Nightly backup"; Get-ChildItem C:\POS\backups
```

> Copy `C:\POS\backups` off the server regularly (NAS / cloud).

## 10. Verify

From another PC:

- [ ] `https://<HostName>/platform/` → sign in as the admin, create a store + store user
- [ ] Sign in at `https://<HostName>/` as the store user, add a product **with an image**, make a test sale
- [ ] `http://<HostName>` redirects to `https://`
- [ ] Restart the server once; the POS comes back up on its own

---

## Updating to a new version

```powershell
Stop-Service POS
Start-ScheduledTask "POS - Nightly backup"      # wait for it: Get-ScheduledTaskInfo "POS - Nightly backup"
git -C C:\POS\repo pull
cd C:\POS\app
& $py -m pip install -r requirements.txt
& $py manage.py migrate --noinput
& $py manage.py setup_archive_db
& $py manage.py collectstatic --noinput
Start-Service POS
```

## Restoring a backup

```powershell
Stop-Service POS
$env:PGPASSFILE = "C:\POS\secrets\pgpass.conf"
& "$pgBin\pg_restore.exe" -h 127.0.0.1 -U pos_user -d pos_system  --clean --if-exists C:\POS\backups\pos_system_<STAMP>.dump
& "$pgBin\pg_restore.exe" -h 127.0.0.1 -U pos_user -d pos_archive --clean --if-exists C:\POS\backups\pos_archive_<STAMP>.dump
Start-Service POS
```

To move data from an old machine: `pg_dump -F c` it there, restore it the same way (add `--no-owner`), copy the old `media` folder into `C:\POS\app\media`, then re-run step 6's `migrate`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| 400 Bad Request | Check `DJANGO_ALLOWED_HOSTS`; re-run the `preserveHostHeader` command (step 8) |
| 403 CSRF failed | `DJANGO_CSRF_TRUSTED_ORIGINS` must start with `https://` |
| Too many redirects | Re-run the `allowedServerVariables` command (step 8) |
| 502.3 Bad Gateway / service won't start | `Get-Content C:\POS\logs\pos.log -Tail 40` (usually `.env` or DB password) |
| No styling | Run `collectstatic`, then `Restart-Service POS` |
| Images missing | Re-run the `media` virtual directory + `icacls` lines (step 8) |
| "Locked" at sign-in | 5 failed attempts → wait 15 minutes |

After any `.env` change: `Restart-Service POS`.
**Never** open ports 8000 or 5432 in the firewall.
