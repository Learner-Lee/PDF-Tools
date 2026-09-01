# PDF 对照 —— 一条命令部署（Windows PowerShell）
#
#   irm https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.ps1 | iex
#
# 已经 clone 过的话，在仓库里直接跑 .\install.ps1 也一样（会先拉取更新）。
#
# 可用开关（先设环境变量再执行）：
#   $env:WITH_VOCAB=1   同时构建难词词库（额外下载约 70MB）
#   $env:NO_START=1     只装不启动
#   $env:PORT=8731      监听端口

$ErrorActionPreference = "Stop"

$RepoUrl   = if ($env:REPO_URL)   { $env:REPO_URL }   else { "https://github.com/Learner-Lee/PDF-Tools.git" }
$Dir       = if ($env:DIR)        { $env:DIR }        else { "PDF-Tools" }
$Port      = if ($env:PORT)       { $env:PORT }       else { "8731" }
$WithVocab = $env:WITH_VOCAB -eq "1"
$NoStart   = $env:NO_START   -eq "1"

function Step($m) { Write-Host "`n▸ $m" -ForegroundColor White }
function Info($m) { Write-Host "  $m" -ForegroundColor DarkGray }
function Die($m)  { Write-Host "`n✗ $m`n" -ForegroundColor Red; exit 1 }

# ── 环境检查 ────────────────────────────────────────────────
Step "检查环境"
if (-not (Get-Command git  -EA SilentlyContinue)) { Die "找不到 Git。请安装：https://git-scm.com/downloads" }
if (-not (Get-Command node -EA SilentlyContinue)) { Die "找不到 Node。请安装 18+：https://nodejs.org/" }

$py = $null
foreach ($c in @("py", "python3", "python")) {
  if (Get-Command $c -EA SilentlyContinue) {
    & $c -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $c; break }
  }
}
if (-not $py) { Die "需要 Python 3.10 或更新版本。请从 https://www.python.org/downloads/ 安装（记得勾选 Add to PATH）。" }

$nodeMajor = [int](node -p "process.versions.node.split('.')[0]")
if ($nodeMajor -lt 18) { Die "需要 Node 18 或更新版本，当前是 $(node -v)。" }

Info "Python  $(& $py -c 'import platform;print(platform.python_version())')  ($py)"
Info "Node    $(node -v)"

# ── 取得代码 ────────────────────────────────────────────────
Step "取得代码"
if ((Test-Path "backend/app/main.py") -and (Test-Path ".git")) {
  Info "已在仓库内，拉取更新"
  git pull --ff-only 2>$null | Out-Null
} elseif (Test-Path "$Dir/.git") {
  Info "$Dir 已存在，拉取更新"
  Set-Location $Dir
  git pull --ff-only 2>$null | Out-Null
} else {
  Info "克隆到 .\$Dir"
  git clone --depth 1 $RepoUrl $Dir
  Set-Location $Dir
}
$Root = (Get-Location).Path

# ── Python 依赖 ─────────────────────────────────────────────
Step "安装 Python 依赖"
if (-not (Test-Path ".venv")) { & $py -m venv .venv }
$VPy = Join-Path $Root ".venv\Scripts\python.exe"
& $VPy -m pip install -q --upgrade pip
& $VPy -m pip install -q -r backend\requirements.txt
Info "完成"

# ── 前端 ────────────────────────────────────────────────────
Step "构建前端"
Set-Location frontend
if (Test-Path "package-lock.json") { npm ci --silent } else { npm install --silent }
npm run build --silent | Out-Null
Set-Location $Root
Info "完成（后端会直接托管构建产物，无需另起前端服务）"

# ── 配置 ────────────────────────────────────────────────────
Step "准备配置"
if (Test-Path ".env") {
  Info ".env 已存在，保持不变"
} else {
  Copy-Item ".env.example" ".env"
  Info "已生成 .env —— 密钥留空，可在启动后的「设置」界面填写"
}

# ── 词库（可选）─────────────────────────────────────────────
if ($WithVocab) {
  Step "构建难词词库"
  Set-Location backend
  & $VPy -m scripts.fetch_wordlists
  & $VPy -m scripts.build_vocab
  Set-Location $Root
} elseif (-not (Test-Path "data\vocab.db")) {
  Step "难词词库（未构建）"
  Info "难词模式需要本地词库。对照翻译与导出不受影响。"
  Info "需要时执行：cd backend; ..\.venv\Scripts\python -m scripts.fetch_wordlists"
  Info "            cd backend; ..\.venv\Scripts\python -m scripts.build_vocab"
}

# ── 启动 ────────────────────────────────────────────────────
Write-Host "`n✓ 部署完成" -ForegroundColor Green -NoNewline
Write-Host "  $Root" -ForegroundColor DarkGray

if ($NoStart) {
  Write-Host "`n启动：cd $Root; .venv\Scripts\python -m uvicorn app.main:app --app-dir backend --port $Port`n"
  exit 0
}

Write-Host "`n在浏览器打开 http://localhost:$Port" -ForegroundColor White
Write-Host "首次使用请点右上角「设置」填入任意 OpenAI 兼容服务的 base_url 与密钥。" -ForegroundColor DarkGray
Write-Host "按 Ctrl+C 停止。`n" -ForegroundColor DarkGray

& $VPy -m uvicorn app.main:app --app-dir backend --port $Port
