# SOS（官方版）在不干扰主驾的前提下的隔离启动工具
#
# 为什么要隔离：两处状态是共享的，且都出过事。
#   ① Harness home（$DSH_HOME，当前用户变量 = E:\DSH\home）：sessions / profiles / 插件 link 目录都在里面。
#      2026-10-26 已发生：用旧版 alpha.1 启动 rc.3 建好的 home → profile 被重建、bundles 重置、link 插件目录被清空。
#   ② Electron profile（%APPDATA%\@deepseek-ai\dsh-desktop）：Cookies（含每次启动一枚的 dsh-auth-*）、
#      localStorage、以及**单实例锁**。主驾在跑时 SOS 会因锁直接 quit（无日志、无窗口）。
#      Electron profile 无法用 --user-data-dir 隔离（该安装拒绝这个参数），只能"换目录"。
#
# 因此真隔离 = 独立 home（环境变量）+ 换掉 Electron profile 目录（改名法）。代价：不能与主驾同时运行。
#
# 用法：
#   -Status    只看现状（默认）
#   -Isolate   备份并换出主驾的 Electron profile，用独立 home 启动 SOS
#   -Restore   把主驾的 Electron profile 换回来（SOS 必须先退出）
#   -CleanCookies  不隔离、只清理累积的 dsh-auth cookie（会同时影响主驾登录态，需重新登录）
#
# 全部操作前后都会打印将要做的事；加 -WhatIf 只演练不动手。

param(
  [switch]$Status,
  [switch]$Isolate,
  [switch]$Restore,
  [switch]$CleanCookies,
  [switch]$WhatIf,
  [int]$KeepNewest = 5,
  [string]$SosHome = "$env:USERPROFILE\SOS-home"
)

$ErrorActionPreference = 'Stop'
$appdata = Join-Path $env:APPDATA '@deepseek-ai'
$profileDir = Join-Path $appdata 'dsh-desktop'
$profileBackup = Join-Path $appdata 'dsh-desktop.main-backup'
$sosProfileLeft = Join-Path $appdata 'dsh-desktop.rc3'
$cookieDb = Join-Path $profileDir 'Network\Cookies'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'backups'

function Show-Status {
  Write-Host "== 现状 ==" -ForegroundColor Cyan
  $procs = Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue
  if ($procs) {
    $paths = $procs | ForEach-Object { try { $_.Path } catch { $null } } | Where-Object { $_ } | Sort-Object -Unique
    Write-Host "  运行中的 Harness：$($procs.Count) 个进程"
    foreach ($p in $paths) { Write-Host "    - $p" }
  } else { Write-Host "  运行中的 Harness：无" }
  Write-Host "  DSH_HOME（用户变量）：$([Environment]::GetEnvironmentVariable('DSH_HOME','User'))"
  Write-Host "  生效中的 profile 目录：$profileDir  $([bool](Test-Path $profileDir))"
  Write-Host "  主驾 profile 备份：    $profileBackup  $([bool](Test-Path $profileBackup))"
  Write-Host "  SOS 上次留下的 profile：$sosProfileLeft  $([bool](Test-Path $sosProfileLeft))"
  Write-Host "  独立 home：            $SosHome  $([bool](Test-Path $SosHome))"
}

# 只找「桌面壳」进程：它们才占着 Electron profile（Cookies / localStorage / 单实例锁）。
# 工作台是 headless 的 node 进程（命令行带 --expose-internals），不用关。
function Get-DesktopShells {
  Get-CimInstance Win32_Process -Filter "Name = 'DeepSeek Harness.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
      $cl = [string]$_.CommandLine
      ($cl -notmatch '--expose-internals') -and ($cl -notmatch 'subprocess-local')
    }
}

function Assert-NoHarness($why) {
  $shells = @(Get-DesktopShells)
  if ($shells.Count -gt 0) {
    $paths = $shells | ForEach-Object { try { $_.ExecutablePath } catch { $null } } | Where-Object { $_ } | Sort-Object -Unique
    Write-Host "[!] $why 需要先退出 DeepSeek Harness **桌面程序**（含托盘图标）。" -ForegroundColor Yellow
    Write-Host "    还在跑的安装：$($paths -join ' ; ')" -ForegroundColor Yellow
    Write-Host "    （工作台的后台进程不用关，它们不占 profile）" -ForegroundColor Yellow
    if (-not $WhatIf) { exit 2 }
  }
}

Show-Status

if (Test-Path $profileBackup) {
  Write-Host ""
  Write-Host "[!] 注意：隔离没有还原。" -ForegroundColor Yellow
  Write-Host "    当前生效的 profile 是隔离时新建的那份；原来的主驾 profile 在：" -ForegroundColor Yellow
  Write-Host "      $profileBackup" -ForegroundColor Yellow
  Write-Host "    想换回原来的：退出所有 Harness → 跑 -Restore" -ForegroundColor Yellow
  Write-Host "    想继续用现在这份：把上面那个目录改名（例如加 -$stamp 后缀），否则下次 -Isolate 会被它挡住" -ForegroundColor Yellow
}

if (-not ($Isolate -or $Restore -or $CleanCookies)) { exit 0 }

# ── 模式一：隔离启动 ───────────────────────────────────────────────
if ($Isolate) {
  Write-Host "`n== 隔离启动 SOS ==" -ForegroundColor Cyan
  Assert-NoHarness "换出 Electron profile"
  if (Test-Path $profileBackup) {
    Write-Host "[!] 已经存在 $profileBackup —— 说明上次隔离没还原。先跑 -Restore。" -ForegroundColor Red
    exit 3
  }
  if (-not (Test-Path $profileDir)) { Write-Host "[!] 找不到 $profileDir" -ForegroundColor Red; exit 1 }

  $dest = Join-Path $backupRoot "sos-isolate-$stamp"
  if ($WhatIf) {
    Write-Host "  [干跑] 会备份 profile → $dest，然后把 $profileDir 改名为 $profileBackup"
    Write-Host "  [干跑] 会用 DSH_HOME=$SosHome 启动 E:\SOS"
    exit 0
  }

  New-Item -ItemType Directory -Path $dest -Force | Out-Null
  Write-Host "  [..] 备份 Electron profile（约 40 MB）→ $dest"
  Copy-Item $profileDir (Join-Path $dest 'dsh-desktop') -Recurse -Force
  Write-Host "  [ok] 备份完成"

  Write-Host "  [..] 换出主驾 profile：$profileDir → $profileBackup"
  Rename-Item -Path $profileDir -NewName 'dsh-desktop.main-backup'

  New-Item -ItemType Directory -Path $SosHome -Force | Out-Null
  Write-Host "  [..] 启动 SOS（DSH_HOME=$SosHome，全新 profile）"
  $env:DSH_HOME = $SosHome
  Start-Process -FilePath 'E:\SOS\DeepSeek Harness.exe' -WorkingDirectory 'E:\SOS'
  Start-Sleep -Seconds 20
  $now = Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue | Where-Object { $_.Path -like 'E:\SOS*' }
  if ($now) {
    Write-Host "  [ok] SOS 已启动（pid: $($now.Id -join ', ')）。这是隔离环境：独立 home + 全新 profile。" -ForegroundColor Green
    Write-Host "       测完：退出 SOS → 跑 -Restore 把主驾 profile 换回来。" -ForegroundColor Cyan
  } else {
    Write-Host "  [x] SOS 没起来。最新崩溃日志：" -ForegroundColor Red
    $logs = Join-Path $profileDir 'logs'
    if (Test-Path $logs) {
      Get-ChildItem $logs -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1 |
        ForEach-Object { Get-Content $_.FullName -Raw }
    } else { Write-Host "     （没有 logs 目录）" }
    Write-Host "  [i] 主驾 profile 仍被换在 $profileBackup，记得 -Restore。" -ForegroundColor Yellow
  }
  exit 0
}

# ── 模式二：还原 ───────────────────────────────────────────────────
if ($Restore) {
  Write-Host "`n== 还原主驾 profile ==" -ForegroundColor Cyan
  Assert-NoHarness "还原 profile"
  if (-not (Test-Path $profileBackup)) {
    Write-Host "  没有待还原的备份（$profileBackup 不存在），可能已经还原过了。" -ForegroundColor Yellow
    exit 0
  }
  if ($WhatIf) {
    Write-Host "  [干跑] 会先把当前 profile 保留成：dsh-desktop.rc3"
    Write-Host "  [干跑] 再把 $profileBackup 换回 $profileDir"
    exit 0
  }
  if (Test-Path $sosProfileLeft) { Remove-Item $sosProfileLeft -Recurse -Force -ErrorAction SilentlyContinue }
  if (Test-Path $profileDir) {
    Write-Host "  [..] 保留 SOS 这次生成的 profile 作参考：→ dsh-desktop.rc3"
    try { Rename-Item -Path $profileDir -NewName 'dsh-desktop.rc3' }
    catch { Write-Host "  [x] 改名失败（多半还被进程占用）：$($_.Exception.Message)" -ForegroundColor Red; exit 4 }
  }
  Write-Host "  [..] 换回主驾 profile：$profileBackup → $profileDir"
  try { Rename-Item -Path $profileBackup -NewName 'dsh-desktop' }
  catch { Write-Host "  [x] 换回失败：$($_.Exception.Message)" -ForegroundColor Red; exit 5 }
  Write-Host "  [ok] 已还原。主驾可以正常启动了。" -ForegroundColor Green
  exit 0
}

# ── 模式三：只清 cookie（不隔离）─────────────────────────────────────
if ($CleanCookies) {
  Write-Host "`n== 只清理 dsh-auth cookie（不隔离）==" -ForegroundColor Cyan
  Write-Host "  [i] 注意：profile 是共享的，清理会同时影响主驾登录态（需要重新登录）。" -ForegroundColor Yellow
  Assert-NoHarness "清理 cookie 库"
  if (-not (Test-Path $cookieDb)) { Write-Host "[!] 找不到 $cookieDb" -ForegroundColor Red; exit 1 }

  $py = @'
import sqlite3, sys
db, dry, keep = sys.argv[1], sys.argv[2] == "1", int(sys.argv[3])
conn = sqlite3.connect(db); cur = conn.cursor()
cur.execute("select count(*) from cookies"); print("  cookie 总数:", cur.fetchone()[0])
cur.execute("select host_key, count(*) from cookies where name like 'dsh-auth%' group by host_key")
rows = cur.fetchall(); print("  dsh-auth 分布:", rows if rows else "（没有）")
if not dry:
    deleted = 0
    for host, _n in rows:
        cur.execute("select rowid from cookies where host_key=? and name like 'dsh-auth%' order by creation_utc desc", (host,))
        for rid in [r[0] for r in cur.fetchall()][keep:]:
            cur.execute("delete from cookies where rowid=?", (rid,)); deleted += 1
    conn.commit(); conn.execute("vacuum")
    cur.execute("select count(*) from cookies"); print("  已删除旧 dsh-auth:", deleted, "；清理后总数:", cur.fetchone()[0])
conn.close()
'@
  $pyFile = Join-Path $env:TEMP "dsh_cookie_clean_$stamp.py"
  Set-Content -Path $pyFile -Value $py -Encoding UTF8
  $dry = if ($WhatIf) { '1' } else { '0' }
  & python $pyFile $cookieDb $dry $KeepNewest
  $code = $LASTEXITCODE
  Remove-Item $pyFile -Force -ErrorAction SilentlyContinue
  if ($code -ne 0) { Write-Host "[!] 读不了 cookie 库（被占用）。先完全退出 Harness。" -ForegroundColor Yellow; exit 3 }
  if ($WhatIf) { Write-Host "  [干跑] 没有改动" -ForegroundColor Cyan }
  exit 0
}
