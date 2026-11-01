# 只把可再分发的源码和必要素材导出成一个全新 Git 历史的公开工作树。
# 本地开发仓库保留原有的内部调研、交接记录和提交历史，不做 reset / clean。
param(
  [Parameter(Mandatory = $true)]
  [string]$Destination
)

$ErrorActionPreference = "Stop"
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$targetRoot = [System.IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $targetRoot) {
  throw "目标目录已存在，拒绝覆盖：$targetRoot"
}
New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null

$files = & git -C $sourceRoot -c core.quotepath=false ls-files --cached --others --exclude-standard
if ($LASTEXITCODE -ne 0) { throw "无法列举工作区文件" }

$skipped = @()
$copied = 0
foreach ($rel in $files) {
  $norm = ($rel -replace '\\', '/')
  if (!$norm) { continue }

  # 内部工作记录、抓取的网页原文、生成缓存、私钥和机器配置不公开。
  if ($norm -match '^(\.git/|\.research/|\.qoder/|\.impeccable/|node_modules/|www/|test/shots-|test/screens/|android/(\.gradle|\.kotlin|build|\.idea)/|android/build-log\.txt$|android/app/build/|android/app/src/main/assets/)') { $skipped += $norm; continue }
  if ($norm -match '(^|/)(local\.properties|llm_providers\.json|providers\.json|secrets\.json|gradle\.properties\.user)$|\.(keystore|jks|p12|pem|key|log|pyc|lanebak|orig)$') { $skipped += $norm; continue }
  if ($norm -match '^(AGENTS\.md|交接说明\.txt|docs/(HANDOVER-.*|AUDIT-TRIAGE.*))$') { $skipped += $norm; continue }
  if ($norm -match '^test/_' -and $norm -ne 'test/_engine_dump.mjs') { $skipped += $norm; continue }

  $ext = [System.IO.Path]::GetExtension($norm).ToLowerInvariant()
  $allowed = @('.js','.mjs','.css','.html','.json','.md','.txt','.py','.ps1',
               '.png','.jpg','.jpeg','.webp','.ico','.svg','.xml','.gradle',
               '.properties','.kt','.java','.bat','.jar','.sh','.yml','.yaml')
  if ($norm -notin @('.gitignore','LICENSE','gradlew','android/gradlew') -and $ext -notin $allowed) { $skipped += $norm; continue }

  $from = Join-Path $sourceRoot $rel
  if (!(Test-Path -LiteralPath $from -PathType Leaf)) { continue }
  $to = Join-Path $targetRoot $rel
  $parent = Split-Path -Parent $to
  if (!(Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  Copy-Item -LiteralPath $from -Destination $to
  $copied++
}
Write-Output "已导出 $copied 个文件；跳过 $($skipped.Count) 个内部/生成文件。"
Write-Output "公开候选目录：$targetRoot"
Write-Output "检查关键排除项："
foreach ($p in @('.git','.research','.qoder','node_modules','www','android/app/jian-release.keystore','backend/llm_providers.json')) {
  $full = Join-Path $targetRoot $p
  if (Test-Path -LiteralPath $full) { throw "公开候选包含禁止项目：$p" }
}
