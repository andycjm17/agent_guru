#!/usr/bin/env bash
# 打包成可分发的安装包：干净 tarball，剔除个人配置 / token / 数据 / 日志。
# 用法: ./package.sh [版本号]   例如 ./package.sh v1
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
VER="${1:-v1}"
NAME="workflow-distiller-$VER"
OUT="$HERE/dist"
STAGE="$OUT/$NAME"

rm -rf "$STAGE"
mkdir -p "$STAGE"

# 要打进包的清单（白名单，避免误带个人/敏感文件）
INCLUDE=(
  distiller          # 全部模块（纯 stdlib）
  ui                 # 单页 UI
  install.sh
  package.sh
  com.workflow-distiller.plist.template
  config.local.example.json
  README.md
  SETUP.md
  LICENSE
  .gitignore
)
# 注：PLAN.md 是内部设计稿（含 v1 个人化背景），不进分发包
for item in "${INCLUDE[@]}"; do
  [ -e "$item" ] && cp -R "$item" "$STAGE/" || echo "  (跳过缺失项: $item)"
done

# 清理打入物里的派生/缓存
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '*.pyc' -delete 2>/dev/null || true

# 显式保证不含敏感/个人文件（双保险）
rm -f "$STAGE/config.local.json" 2>/dev/null || true
rm -rf "$STAGE/data" "$STAGE/logs" 2>/dev/null || true
# 空数据骨架（部署后由 install.sh 建，这里给个占位说明）
mkdir -p "$STAGE/data/state"
printf '%s\n' "运行后自动填充：digests.json / map.json / savings_ledger.jsonl 等" > "$STAGE/data/README.txt"

chmod +x "$STAGE/install.sh" "$STAGE/package.sh" 2>/dev/null || true

TARBALL="$OUT/$NAME.tar.gz"
tar -czf "$TARBALL" -C "$OUT" "$NAME"

echo "✓ 安装包: $TARBALL"
echo "  解包后: tar -xzf $NAME.tar.gz && cd $NAME && ./install.sh"
echo "  内容清单:"
tar -tzf "$TARBALL" | sed 's/^/    /' | head -40
# 敏感泄漏自检
if tar -tzf "$TARBALL" | grep -q "config.local.json$"; then
  echo "  ✗ 警告：包内含 config.local.json（应被排除）！"; exit 1
fi
echo "  ✓ 已确认不含 config.local.json / data 快照 / logs"
