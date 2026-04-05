#!/usr/bin/env bash
# 将本仓库作为 lark-meeting skill 安装到 ~/.agents/skills，
# 并在 Claude Code 的 ~/.claude/skills 下创建指向该目录的软链接。
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SKILL_NAME="lark-meeting"
AGENTS_SKILLS="${HOME}/.agents/skills"
DEST="${AGENTS_SKILLS}/${SKILL_NAME}"
CLAUDE_SKILLS="${HOME}/.claude/skills"
LINK="${CLAUDE_SKILLS}/${SKILL_NAME}"

echo "==> 安装 ${SKILL_NAME}"
echo "    源目录: ${SCRIPT_DIR}"
echo "    拷贝到: ${DEST}"
echo "    软链接: ${LINK} -> ${DEST}"

mkdir -p "${AGENTS_SKILLS}"

EXCLUDES=(
  --exclude='.git/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='.DS_Store'
)

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "${EXCLUDES[@]}" "${SCRIPT_DIR}/" "${DEST}/"
else
  rm -rf "${DEST}"
  mkdir -p "${DEST}"
  (cd "${SCRIPT_DIR}" && tar cf - \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.DS_Store' \
    .) | (cd "${DEST}" && tar xf -)
fi

link_claude_skills() {
  mkdir -p "${CLAUDE_SKILLS}"
  # -n：若目标已是目录的 symlink，不解析，直接替换该 symlink（BSD/macOS）
  ln -sfn "${DEST}" "${LINK}"
}

if ! link_claude_skills 2>/dev/null; then
  echo ""
  echo "无法在 ${CLAUDE_SKILLS} 创建软链接（常见原因：目录属主为 root）。请在本机执行："
  echo "  sudo mkdir -p '${CLAUDE_SKILLS}'"
  echo "  sudo ln -sfn '${DEST}' '${LINK}'"
  exit 1
fi

echo "==> 完成。"
