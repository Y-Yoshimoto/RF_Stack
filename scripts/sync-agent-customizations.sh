#!/usr/bin/env bash
# .github/ 配下のエージェント設定ファイルを .claude/ に同期するスクリプト
# コピー先のファイルは誤編集防止のため、既定で read-only (chmod 444) に設定される。
# ディレクトリは read-only にしない(同期の再実行と読み取りのため、既定のパーミッションを維持する)。
# 同期元に存在しないファイルは削除されないため、リネーム/削除時は同期先の後始末を手動で行うこと。
# 使用例:
#   bash scripts/sync-agent-customizations.sh         # 同期を実行
#   bash scripts/sync-agent-customizations.sh sync    # 同期を実行(明示)
#   bash scripts/sync-agent-customizations.sh --check # チェックのみ
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 同期ペア(src:dest ディレクトリ単位の同期)
PAIRS=(
    "${REPO_ROOT}/.github/skills:${REPO_ROOT}/.claude/skills"
    "${REPO_ROOT}/.github/agents:${REPO_ROOT}/.claude/agents"
    "${REPO_ROOT}/.github/instructions:${REPO_ROOT}/.claude/instructions"
)

usage() {
    cat <<'USAGE'
Usage: scripts/sync-agent-customizations.sh [sync|--check]

  sync (既定)  .github/ 配下の設定ファイルを .claude/ に同期する
  --check      同期漏れがないかチェックのみ行う(差分があれば exit 1)
USAGE
}

# モードの判定(未知の引数は誤って同期が走らないようにエラーとする)
mode="sync"
case "${1:-}" in
    "" | sync) mode="sync" ;;
    --check | check) mode="check" ;;
    -h | --help)
        usage
        exit 0
        ;;
    *)
        echo "Unknown argument: $1" >&2
        usage >&2
        exit 2
        ;;
esac

# 同期元 -> 同期先へコピーし、コピーしたファイルのみ read-only にする
sync_dir() {
    local src="$1" dest="$2"
    # 過去に read-only 化されたディレクトリ/ファイルを書き込み可能に戻してから上書きする
    if [[ -d "$dest" ]]; then
        chmod -R u+wX "$dest"
    fi
    mkdir -p "$dest"
    # "/." を使うことで、同期元が空でもドットファイルがあっても失敗しない
    cp -rf "$src"/. "$dest"/
    # ディレクトリは通常の権限に揃え、ファイルのみ read-only にする
    find "$dest" -type d -exec chmod 755 {} +
    find "$dest" -type f -exec chmod 444 {} +
}

# 差分の有無を判定する
# diff は読み取りに失敗しても exit 0 を返すことがあるため、標準エラー出力も差分として扱う
compare_dir() {
    local src="$1" dest="$2" output=""
    if [[ ! -d "$dest" ]]; then
        echo "Missing destination: $dest"
        return 1
    fi
    output="$(diff -rq "$src" "$dest" 2>&1)" || {
        [[ -n "$output" ]] && printf '%s\n' "$output"
        return 1
    }
    if [[ -n "$output" ]]; then
        printf '%s\n' "$output"
        return 1
    fi
    return 0
}

status=0
for pair in "${PAIRS[@]}"; do
    src="${pair%%:*}"
    dest="${pair##*:}"

    # 同期元が未作成の場合はスキップする(clone 直後や新規ディレクトリ追加前を想定)
    if [[ ! -d "$src" ]]; then
        echo "Skipped (no source): $src"
        continue
    fi

    if [[ "$mode" == "check" ]]; then
        if compare_dir "$src" "$dest"; then
            echo "No differences for $src -> $dest"
        else
            echo "Differences found for $src -> $dest"
            status=1
        fi
    else
        echo "Syncing $src -> $dest"
        sync_dir "$src" "$dest"
    fi
done

if [[ "$mode" == "check" ]] && [ $status -ne 0 ]; then
    echo "scripts/sync-agent-customizations.sh を実行して同期すること"
fi

exit $status
