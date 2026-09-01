#!/usr/bin/env bash
# PDF 对照 —— 一条命令部署
#
#   curl -fsSL https://raw.githubusercontent.com/Learner-Lee/PDF-Tools/main/install.sh | bash
#
# 已经 clone 过的话，在仓库里直接跑 ./install.sh 也一样（会先拉取更新）。
#
# 可用开关（通过环境变量传入，管道运行时也生效）：
#   WITH_VOCAB=1   同时构建难词词库（额外下载约 70MB，编译成 39MB）
#   NO_START=1     只装不启动
#   PORT=8731      监听端口
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Learner-Lee/PDF-Tools.git}"
DIR="${DIR:-PDF-Tools}"
PORT="${PORT:-8731}"
WITH_VOCAB="${WITH_VOCAB:-0}"
NO_START="${NO_START:-0}"

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; OFF=$'\033[0m'
step() { printf "\n%s▸ %s%s\n" "$BOLD" "$1" "$OFF"; }
info() { printf "  %s%s%s\n" "$DIM" "$1" "$OFF"; }
die()  { printf "\n%s✗ %s%s\n\n" "$RED" "$1" "$OFF" >&2; exit 1; }

# ── 环境检查 ────────────────────────────────────────────────
step "检查环境"

need() { command -v "$1" >/dev/null 2>&1 || die "找不到 $1。$2"; }
need git "请先安装 Git：https://git-scm.com/downloads"
need node "请先安装 Node 18+：https://nodejs.org/"

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 &&
     "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || die "需要 Python 3.10 或更新版本。请从 https://www.python.org/downloads/ 安装。"

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 18 ] || die "需要 Node 18 或更新版本，当前是 $(node -v)。"

info "Python  $("$PY" -c 'import platform;print(platform.python_version())')  ($PY)"
info "Node    $(node -v)"

# ── 取得代码 ────────────────────────────────────────────────
step "取得代码"
if [ -f "backend/app/main.py" ] && [ -d ".git" ]; then
  info "已在仓库内，拉取更新"
  git pull --ff-only 2>/dev/null || info "拉取跳过（有本地改动或无网络）"
elif [ -d "$DIR/.git" ]; then
  info "$DIR 已存在，拉取更新"
  cd "$DIR"
  git pull --ff-only 2>/dev/null || info "拉取跳过（有本地改动或无网络）"
else
  info "克隆到 ./$DIR"
  git clone --depth 1 "$REPO_URL" "$DIR"
  cd "$DIR"
fi
ROOT="$(pwd)"

# ── Python 依赖 ─────────────────────────────────────────────
step "安装 Python 依赖"
[ -d .venv ] || "$PY" -m venv .venv
VPY=".venv/bin/python"
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r backend/requirements.txt
info "完成"

# ── 前端 ────────────────────────────────────────────────────
step "构建前端"
cd frontend
if [ -f package-lock.json ]; then npm ci --silent; else npm install --silent; fi
npm run build --silent >/dev/null
cd "$ROOT"
info "完成（后端会直接托管构建产物，无需另起前端服务）"

# ── 配置 ────────────────────────────────────────────────────
step "准备配置"
if [ -f .env ]; then
  info ".env 已存在，保持不变"
else
  cp .env.example .env
  info "已生成 .env —— 密钥留空，可在启动后的「设置」界面填写"
fi

# ── 词库（可选）─────────────────────────────────────────────
if [ "$WITH_VOCAB" = "1" ]; then
  step "构建难词词库"
  cd backend
  "../$VPY" -m scripts.fetch_wordlists
  "../$VPY" -m scripts.build_vocab
  cd "$ROOT"
elif [ ! -f data/vocab.db ]; then
  step "难词词库（未构建）"
  info "难词模式需要本地词库。对照翻译与导出不受影响。"
  info "需要时执行：cd backend && ../.venv/bin/python -m scripts.fetch_wordlists"
  info "            cd backend && ../.venv/bin/python -m scripts.build_vocab"
fi

# ── 启动 ────────────────────────────────────────────────────
printf "\n%s✓ 部署完成%s  %s%s%s\n" "$GREEN" "$OFF" "$DIM" "$ROOT" "$OFF"

if [ "$NO_START" = "1" ]; then
  printf "\n启动：%scd %s && .venv/bin/python -m uvicorn app.main:app --app-dir backend --port %s%s\n\n" \
    "$BOLD" "$ROOT" "$PORT" "$OFF"
  exit 0
fi

printf "\n%s在浏览器打开 http://localhost:%s%s\n" "$BOLD" "$PORT" "$OFF"
printf "%s首次使用请点右上角「设置」填入任意 OpenAI 兼容服务的 base_url 与密钥。%s\n" "$DIM" "$OFF"
printf "%s按 Ctrl+C 停止。%s\n\n" "$DIM" "$OFF"

exec "$VPY" -m uvicorn app.main:app --app-dir backend --port "$PORT"
