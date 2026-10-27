# uninstall.ps1 — 工作台卸载（双击 uninstall.cmd 就会跑这个）
#
# 默认是**演练**：只打印会做什么，一个文件都不动（和 `python tools\wb.py uninstall` 一致）。
# 真要卸载就加 -Apply。
#
# 四种用法：
#   uninstall.ps1                 演练（安全，推荐先看一遍）
#   uninstall.ps1 -Apply          停服务 + 删三个只指向本目录的快捷方式（**保留文件**）
#   uninstall.ps1 -Apply -Purge   连目录一起删（延迟 2 秒自删，避免删到自己）
#   uninstall.ps1 -Apply -Detach  顺带把接入层从你的 harness profile 里摘掉（要重启那个 harness 才生效）
#
# 安全边界：
#   · 只停本目录的 serve / watchdog / supervisor，只删**参数里含本目录路径**的快捷方式
#     （同一台机器可能有多套工作台，别把别的套删了）
#   · 绝不删除你的 harness（E:\SSS 之类），-Detach 也只是改它 profile 的 package.json 并先备份

param(
  [switch]$Apply,
  [switch]$Purge,
  [switch]$Detach,
  [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  DSH 工作台 · 卸载" -ForegroundColor Cyan
Write-Host "  目录：$here" -ForegroundColor DarkGray
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

# ① 找 python（优先 PATH 里的 python，其次 py 启动器）
$py = $null
foreach ($cand in @('python', 'py')) {
  $cmd = Get-Command $cand -ErrorAction SilentlyContinue
  if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) {
  Write-Host "[x] 没找到 Python。卸载脚本自己也需要 Python 来读配置、清快捷方式。" -ForegroundColor Red
  Write-Host "    如果只是想把目录删掉，直接删除本文件夹即可（先确认没有工作台进程在跑）。"
  exit 1
}

$wb = Join-Path $here 'tools\wb.py'
if (-not (Test-Path $wb)) {
  Write-Host "[x] 找不到 tools\wb.py —— 这个目录可能已经被破坏。" -ForegroundColor Red
  Write-Host "    想彻底清理就直接删除本文件夹。"
  exit 1
}

# 关键：把**当前目录挪出工作台根**。-Purge 的延迟删除脚本由 wb.py 写，
# 但 Windows 只要还有进程 cwd 在目标树下，rmdir 就会「删得掉文件、删不掉目录」
# （双击 uninstall.cmd 的默认行为就是 cd 进根目录 → 2026-10-27 真机验收踩到）。
Set-Location $env:TEMP

$args = @($wb, 'uninstall')
if ($Apply)  { $args += '--apply' }
if ($Purge)  { $args += '--purge' }
if ($Detach) { $args += '--detach' }

if (-not $Apply) {
  Write-Host "[i] 这是演练：不会改动任何东西。真要卸载请加 -Apply（连文件一起删再加 -Purge）。" -ForegroundColor Yellow
  Write-Host ""
}

& $py @args
$code = $LASTEXITCODE

if ($Apply -and $Purge) {
  Write-Host ""
  Write-Host "[ok] 卸载指令已执行。若目录还在，说明有进程占用，关掉后手动删除本文件夹即可。" -ForegroundColor Green
}

if (-not $NoPause) {
  Write-Host ""
  Read-Host "按回车关闭窗口"
}
exit $code
