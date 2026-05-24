#!/usr/bin/env bash
#
# macOS launchd インストールスクリプト
#
# 動作:
#  1. plist 内の __PROJECT_ROOT__ プレースホルダを実パスに置換
#  2. ~/Library/LaunchAgents/ にコピー
#  3. launchctl load で常駐起動
#
# 使い方:
#   bash scripts/install_launchd.sh        # インストール
#   bash scripts/install_launchd.sh stop   # 停止
#   bash scripts/install_launchd.sh status # 状態確認

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
PLIST_NAMES=(
  "com.vifight.tiktok-bot"
  "com.vifight.tiktok-pipeline"
)

OS_NAME="$(uname -s)"
if [[ "${OS_NAME}" != "Darwin" ]]; then
  echo "エラー: このスクリプトは macOS 専用です (現在: ${OS_NAME})"
  exit 1
fi

cmd="${1:-install}"

case "${cmd}" in
  install)
    if [[ ! -f "${PROJECT_ROOT}/.venv/bin/python" ]]; then
      echo "警告: .venv が見つかりません。先に仮想環境を作成してください:"
      echo "  cd ${PROJECT_ROOT}"
      echo "  python3.11 -m venv .venv"
      echo "  source .venv/bin/activate"
      echo "  pip install -r requirements.txt"
      exit 1
    fi

    mkdir -p "${LAUNCH_AGENTS_DIR}"
    mkdir -p "${PROJECT_ROOT}/logs"

    for name in "${PLIST_NAMES[@]}"; do
      src="${PROJECT_ROOT}/launchd/${name}.plist"
      dst="${LAUNCH_AGENTS_DIR}/${name}.plist"

      if [[ ! -f "${src}" ]]; then
        echo "警告: ${src} が見つかりません"
        continue
      fi

      # __PROJECT_ROOT__ を実パスに置換
      sed "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" "${src}" > "${dst}"
      echo "配置: ${dst}"

      # 既存があれば unload
      if launchctl list | grep -q "${name}"; then
        launchctl unload "${dst}" 2>/dev/null || true
      fi

      launchctl load "${dst}"
      echo "起動: ${name}"
    done

    echo ""
    echo "✓ インストール完了"
    echo "  Bot:       常駐起動(自動再起動)"
    echo "  Pipeline:  毎日 17:00 起動"
    echo ""
    echo "状態確認: bash scripts/install_launchd.sh status"
    ;;

  stop)
    for name in "${PLIST_NAMES[@]}"; do
      dst="${LAUNCH_AGENTS_DIR}/${name}.plist"
      if [[ -f "${dst}" ]]; then
        launchctl unload "${dst}" 2>/dev/null || true
        echo "停止: ${name}"
      fi
    done
    echo "✓ 停止完了"
    ;;

  uninstall)
    for name in "${PLIST_NAMES[@]}"; do
      dst="${LAUNCH_AGENTS_DIR}/${name}.plist"
      if [[ -f "${dst}" ]]; then
        launchctl unload "${dst}" 2>/dev/null || true
        rm "${dst}"
        echo "削除: ${dst}"
      fi
    done
    echo "✓ アンインストール完了"
    ;;

  status)
    echo "--- launchctl ---"
    for name in "${PLIST_NAMES[@]}"; do
      if launchctl list | grep -q "${name}"; then
        line=$(launchctl list | grep "${name}")
        echo "起動中: ${line}"
      else
        echo "停止中: ${name}"
      fi
    done
    echo ""
    echo "--- ログ (直近10行) ---"
    for log in launchd_bot.out.log launchd_bot.err.log launchd_pipeline.out.log launchd_pipeline.err.log; do
      path="${PROJECT_ROOT}/logs/${log}"
      if [[ -f "${path}" ]]; then
        echo ""
        echo "[${log}]"
        tail -n 10 "${path}"
      fi
    done
    ;;

  *)
    echo "使い方: $0 {install|stop|uninstall|status}"
    exit 1
    ;;
esac
