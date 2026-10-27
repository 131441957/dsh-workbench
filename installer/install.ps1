# install.ps1 — 工作台一键安装（双击 install.cmd 就会跑这个）
#
# 做的事（等价于命令行 `python tools\wb.py setup`）：
#   ① 找 python ② 探测目标 harness ③ 兼容体检（不兼容直接停）④ 装运行时 + profile
#   ⑤ 把接入层装进你的 harness profile（已装过就跳过）⑥ 打印入口地址
#
# 安全边界：
#   · 只往**本目录**写东西（app/ home/ state/ 等），不碰你的 harness 安装目录
#   · 唯一改到外部的是你的 harness profile 的 package.json（加一条软依赖桥），
#     而且会先备份；想撤销就 `python tools\wb.py detach --apply`
#   · 重复双击是安全的（幂等；运行时已存在就不复制）
#
# 想先看会做什么：powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun

param(
  [switch]$DryRun,
  [switch]$NoAttach,
  [switch]$OpenPage,
  [switch]$NoPause,
  [switch]$NoShortcuts
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  DSH 工作台 · 一键安装" -ForegroundColor Cyan
Write-Host "  目录：$here" -ForegroundColor DarkGray
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# ① 找 python（优先 py 启动器，其次 PATH 里的 python）
$py = $null
foreach ($cand in @('python', 'py')) {
  $cmd = Get-Command $cand -ErrorAction SilentlyContinue
  if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) {
  Write-Host "[x] 没找到 Python。请先装 Python 3.10+ 并勾选 Add to PATH。" -ForegroundColor Red
  Write-Host "    下载：https://www.python.org/downloads/windows/"
  exit 1
}
$ver = & $py -c "import sys;print('.'.join(map(str,sys.version_info[:2])))" 2>&1
Write-Host "[ok] Python $ver  ($py)" -ForegroundColor Green

$wb = Join-Path $here 'tools\wb.py'
if (-not (Test-Path $wb)) {
  Write-Host "[x] 找不到 tools\wb.py —— 你是不是只拷了部分文件？请解压完整分发包。" -ForegroundColor Red
  exit 1
}

$args = @($wb, 'setup', '--yes')
if ($NoAttach) { $args += '--no-attach' }
if ($OpenPage -and -not $DryRun) { $args += '--open' }

# 演练副本（不是常驻安装）请加 -NoShortcuts：否则会把桌面「DSH 工作台」和开机自启
# 改成指向这个副本，回头删掉副本就变死链（2026-10-27 踩过）。
if ($NoShortcuts) {
  $env:DSH_WB_NO_SHORTCUTS = '1'
  Write-Host "[i] 不改桌面快捷方式与开机自启（-NoShortcuts）" -ForegroundColor DarkGray
}

if ($DryRun) {
  Write-Host ""
  Write-Host "[干跑] 会执行：" -ForegroundColor Yellow
  Write-Host "    $py $($args -join ' ')" -ForegroundColor Yellow
  Write-Host "[干跑] 不改任何东西。去掉 -DryRun 再跑一次才是真装。" -ForegroundColor Yellow
  exit 0
}

Write-Host ""
Write-Host "[..] 开始安装（首次约 30~100 秒，大头是复制运行时）。中途别关窗口。" -ForegroundColor Cyan
Write-Host ""

& $py @args
$code = $LASTEXITCODE

Write-Host ""
if ($code -eq 0) {
  Write-Host "==============================================" -ForegroundColor Green
  Write-Host "  安装完成" -ForegroundColor Green
  Write-Host "  · 打开页面：桌面「DSH 工作台」，或 python tools\wb.py page" -ForegroundColor Green
  Write-Host "  · 看状态：python tools\wb.py status" -ForegroundColor Green
  Write-Host "  · 改坏了能回：python tools\wb.py backups / restore --from latest" -ForegroundColor Green
  Write-Host "==============================================" -ForegroundColor Green
} else {
  Write-Host "==============================================" -ForegroundColor Red
  Write-Host "  安装没成功（退出码 $code）" -ForegroundColor Red
  Write-Host "  把上面最后 20 行发给我/贴到 issue 里就能定位。" -ForegroundColor Red
  Write-Host "==============================================" -ForegroundColor Red
}
Write-Host ""
if (-not $NoPause) { Read-Host "按回车关闭窗口" }
