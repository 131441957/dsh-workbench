# 修复 E:\SOS（官方 0.2.1-rc.3）启动失败
#
# 背景（2026-10-27 实测）：
#   1) 主驾（E:\SSS）在跑时，SOS 会被 Electron 单实例锁挡住 → 秒退、无日志（这是设计行为）。
#   2) 主驾关闭后，SOS 曾在 welcome 阶段报 `desktop welcome: Web authentication failed`。
#      welcome 会用 Electron session fetch 带上 cookie 请求本机 launch URL，**非 2xx 就报这句**。
#      DSH 每次启动都会发一枚 `dsh-auth-<随机>` cookie，且 cookie 不按端口隔离 →
#      127.0.0.1 下越攒越多，请求头接近 Node 的 16KB 上限时就会 431/401。
#
# 本脚本做三件事：备份 → 只保留最新的几条 dsh-auth cookie → 启动 SOS。
# 必须在**没有 DeepSeek Harness 进程**时运行（先完全退出主驾）。
#
# 用法（在 PowerShell 里）：
#   powershell -ExecutionPolicy Bypass -File E:\DSH-WORKBENCH\tools\fix-sos-start.ps1 -WhatIf
#   powershell -ExecutionPolicy Bypass -File E:\DSH-WORKBENCH\tools\fix-sos-start.ps1
#   powershell -ExecutionPolicy Bypass -File E:\DSH-WORKBENCH\tools\fix-sos-start.ps1 -Launch

param(
  [switch]$WhatIf,
  [switch]$Launch,
  [int]$KeepNewest = 5,
  [string]$CookieDb = ""
)

$ErrorActionPreference = 'Stop'
$cookieDb = if ($CookieDb) { $CookieDb } else { Join-Path $env:APPDATA '@deepseek-ai\dsh-desktop\Network\Cookies' }
$backupRoot = 'E:\DSH-WORKBENCH\backups'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

Write-Host "== DSH 启动修复（SOS / rc.3）==" -ForegroundColor Cyan

# ① 有进程就停（指定 -CookieDb 时视为离线/演练模式，跳过这一步）
$procs = Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue
if ($procs -and -not $CookieDb) {
  Write-Host "[!] 还有 DeepSeek Harness 在运行（pid: $($procs.Id -join ', ')）。" -ForegroundColor Yellow
  Write-Host "    单实例锁会挡住 SOS，而且 cookie 库被独占。请先完全退出它们再跑本脚本。" -ForegroundColor Yellow
  if (-not $WhatIf) { exit 2 }
}

if (-not (Test-Path $cookieDb)) {
  Write-Host "[!] 找不到 cookie 库：$cookieDb" -ForegroundColor Red
  exit 1
}

# ② 备份
if (-not $WhatIf) {
  $dest = Join-Path $backupRoot "sos-cookie-fix-$stamp"
  New-Item -ItemType Directory -Path $dest -Force | Out-Null
  Copy-Item $cookieDb (Join-Path $dest 'Cookies') -Force
  foreach ($extra in @('Cookies-journal', 'Local State')) {
    $p = Join-Path (Split-Path $cookieDb) $extra
    if (Test-Path $p) { Copy-Item $p (Join-Path $dest $extra) -Force }
  }
  Write-Host "[ok] 已备份到 $dest" -ForegroundColor Green
}

# ③ 统计 / 清理 dsh-auth cookie（保留最新 $KeepNewest 条）
$py = @'
import sqlite3, sys, os
db = sys.argv[1]
dry = sys.argv[2] == "1"
keep = int(sys.argv[3])
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("select count(*) from cookies", )
total = cur.fetchone()[0]
cur.execute("select host_key, count(*) from cookies where name like 'dsh-auth%' group by host_key order by count(*) desc")
auth_by_host = cur.fetchall()
print(f"cookie 总数: {total}")
print("dsh-auth 分布:", auth_by_host if auth_by_host else "（没有）")
cur.execute("select sum(length(host_key)+length(name)+length(coalesce(value,''))+length(coalesce(encrypted_value,''))) from cookies")
print("cookie 内容总字节:", cur.fetchone()[0])
if not dry:
    deleted = 0
    for host, _n in auth_by_host:
        cur.execute("select rowid from cookies where host_key=? and name like 'dsh-auth%' order by creation_utc desc", (host,))
        rows = [r[0] for r in cur.fetchall()]
        for rid in rows[keep:]:
            cur.execute("delete from cookies where rowid=?", (rid,))
            deleted += 1
    conn.commit()
    conn.execute("vacuum")
    cur.execute("select count(*) from cookies")
    print(f"已删除旧 dsh-auth: {deleted} 条；清理后总数: {cur.fetchone()[0]}")
conn.close()
'@
$pyFile = Join-Path $env:TEMP "sos_cookie_fix_$stamp.py"
Set-Content -Path $pyFile -Value $py -Encoding UTF8

$dryFlag = if ($WhatIf) { '1' } else { '0' }
& python $pyFile $cookieDb $dryFlag $KeepNewest
if ($LASTEXITCODE -ne 0) {
  Write-Host "[!] 读不了 cookie 库（多半被运行中的 DeepSeek Harness 独占）。" -ForegroundColor Yellow
  Write-Host "    先完全退出它（包括托盘图标），再跑本脚本。" -ForegroundColor Yellow
  Remove-Item $pyFile -Force -ErrorAction SilentlyContinue
  exit 3
}
if (-not $WhatIf) { Remove-Item $pyFile -Force -ErrorAction SilentlyContinue }

if ($WhatIf) {
  Write-Host "[干跑] 没有改动。确认无误后去掉 -WhatIf 再跑一次。" -ForegroundColor Cyan
  exit 0
}

# ④ 启动 SOS（用它自己的 home，别碰主驾 home）
$sosHome = 'E:\SOS-test\home'
New-Item -ItemType Directory -Path $sosHome -Force | Out-Null
if ($Launch) {
  Write-Host "[..] 启动 E:\SOS（DSH_HOME=$sosHome）" -ForegroundColor Cyan
  $env:DSH_HOME = $sosHome
  Start-Process -FilePath 'E:\SOS\DeepSeek Harness.exe' -WorkingDirectory 'E:\SOS'
  Start-Sleep -Seconds 15
  $now = Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue
  if ($now) { Write-Host "[ok] 已启动（pid: $($now.Id -join ', ')）" -ForegroundColor Green }
  else {
    Write-Host "[x] 还是没起来。最新崩溃日志：" -ForegroundColor Red
    Get-ChildItem (Join-Path $env:APPDATA '@deepseek-ai\dsh-desktop\logs') -File |
      Sort-Object LastWriteTime -Descending | Select-Object -First 1 |
      ForEach-Object { Get-Content $_.FullName -Raw }
  }
} else {
  Write-Host "[提示] cookie 已清理。现在手动启动 E:\SOS\DeepSeek Harness.exe 试试；要脚本自动启动就加 -Launch。" -ForegroundColor Cyan
}
