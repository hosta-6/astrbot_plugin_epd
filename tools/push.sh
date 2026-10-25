#!/usr/bin/env bash
# ============================================================
#  MoInk 墨水屏推图（默认走标准调色管线 epd_color.py）
# ------------------------------------------------------------
#  ./push.sh 图片路径                  按定标参数处理并推上屏
#  ./push.sh 图片路径 --foot "10.25"   改底部小字
#  ./push.sh 图片路径 --title "NINE" --sub "cat"
#  ./push.sh --text "要说的话"         纯文字大字（不走调色）
#  ./push.sh 图片路径 --save           同时存进板子图库
#  ./push.sh 图片路径 --raw            跳过调色直接推
#
#  环境变量
#    EPD_DEV     板子地址，默认 http://192.168.4.1（板子开的热点网关）
#    EPD_RELAY   非直连时用：hosta@127.0.0.1:2222，由那台机器 curl 到板子
#    EPD_SSH_KEY EPD_RELAY 用的私钥，默认 ~/.ssh/id_ed25519
#    PYTHON      python 解释器，默认 python3（需装 numpy pillow）
# ============================================================
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
DEV="${EPD_DEV:-http://192.168.4.1}"
RELAY="${EPD_RELAY:-}"
KEY="${EPD_SSH_KEY:-$HOME/.ssh/id_ed25519}"

BIN="${TMPDIR:-/tmp}/epd_frame.bin"
SAVE=""; RAW=0; SRC=""; TEXT=""; ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --save)  SAVE="?save=1"; shift ;;
    --raw)   RAW=1; shift ;;
    --text)  TEXT="$2"; shift 2 ;;
    --title) ARGS+=(--title "$2"); shift 2 ;;
    --sub)   ARGS+=(--sub "$2"); shift 2 ;;
    --foot)  ARGS+=(--foot "$2"); shift 2 ;;
    --focus) ARGS+=(--focus "$2"); shift 2 ;;
    -*)      ARGS+=("$1"); shift ;;
    *)       SRC="$1"; shift ;;
  esac
done

# ---------- 1. 生帧 ----------
if [ -n "$TEXT" ]; then
  "$PY" "$DIR/epd_frame.py" --text "$TEXT" --out "$BIN" >/dev/null
elif [ -n "$SRC" ]; then
  [ -f "$SRC" ] || { echo "找不到文件: $SRC"; exit 1; }
  case "$SRC" in
    *.png|*.jpg|*.jpeg|*.webp|*.bmp|*.PNG|*.JPG)
      if [ "$RAW" = "1" ]; then
        cp "$SRC" "$BIN"
      else
        "$PY" "$DIR/epd_color.py" "$SRC" --out "$BIN" \
          --preview "$DIR/std_preview.png" --photo-preview "$DIR/std_photo.png" \
          "${ARGS[@]}" | sed 's/^/  /'
      fi ;;
    *) cp "$SRC" "$BIN" ;;
  esac
else
  "$PY" "$DIR/epd_frame.py" --out "$BIN" >/dev/null
fi

# ---------- 2. 上屏 ----------
T1=$(date +%s%N); T2=$T1; RESP=""

if [ -z "$RELAY" ]; then
  # 直连：运行本脚本的机器自己就在板子热点/同一网段里
  RESP=$(curl -sS --max-time 60 --noproxy "*" -X POST --data-binary "@$BIN" \
    -H "Content-Type: application/octet-stream" "$DEV/api/frame$SAVE" 2>&1 | tr -d '\r\n')
else
  # 中转：脚本所在机器够不到板子，借 EPD_RELAY 那台（接着板子热点）去 curl
  HOST="${RELAY%@*}"; PORT="${RELAY##*:}"; USER_="${RELAY%%@*}"
  SSHOPT=(-p "$PORT" -i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10)
  REMOTE="${TMPDIR:-C:/Users/Public}/epd_frame.bin"
  scp "${SSHOPT[@]}" "$BIN" "$RELAY:$REMOTE" >/dev/null 2>&1
  T1=$(date +%s%N)
  RESP=$(ssh "${SSHOPT[@]}" "$RELAY" \
    "curl.exe -sS --max-time 60 --noproxy \"*\" -X POST --data-binary \"@$REMOTE\" -H \"Content-Type: application/octet-stream\" \"$DEV/api/frame$SAVE\"" 2>&1 \
    | grep -a -v 'Warning: Permanently' | grep -a -v CLIXML | tr -d '\r\n' || true)
fi
T2=$(date +%s%N)

if echo "$RESP" | grep -q "OK"; then
  echo "✅ 上屏成功 | $(stat -c %s "$BIN" 2>/dev/null || stat -f %z "$BIN")B | $(( (T2-T1)/1000000 ))ms | ${SAVE:-仅显示}"
  [ -f "$DIR/std_preview.png" ] && echo "   预览: $DIR/std_preview.png"
else
  echo "❌ 推送失败 | 响应: $RESP"; exit 1
fi
