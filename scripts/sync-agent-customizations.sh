#!/usr/bin/env bash
# .github/ 配下のエージェント設定ファイルを .claude/ に同期するスクリプト
# コピー先のファイルは誤編集防止のため、既定で read-only (chmod 444) に設定される。
# ディレクトリは read-only にしない(同期の再実行と読み取りのため、既定のパーミッションを維持する)。
# 既定ではコピーのみで削除は伝播しない。--prune を付けた場合のみ、同期元に存在しない
# ファイル/ディレクトリを同期先から削除する(削除対象は標準出力に列挙する)。
# 使用例:
#   bash scripts/sync-agent-customizations.sh              # 同期を実行
#   bash scripts/sync-agent-customizations.sh sync         # 同期を実行(明示)
#   bash scripts/sync-agent-customizations.sh sync --prune # 同期し、孤児ファイルを削除
#   bash scripts/sync-agent-customizations.sh --check      # チェックのみ
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 同期ペア(src:dest ディレクトリ単位の同期)
# .github/instructions/ は GitHub Copilot 専用(applyTo フロントマターで対象を絞る)であり、
# Claude Code 側の対応機構はサブディレクトリの CLAUDE.md のため、同期対象に含めない。
PAIRS=(
    "${REPO_ROOT}/.github/skills:${REPO_ROOT}/.claude/skills"
    "${REPO_ROOT}/.github/agents:${REPO_ROOT}/.claude/agents"
)

usage() {
    cat <<'USAGE'
Usage: scripts/sync-agent-customizations.sh [sync|--check] [--prune]

  sync (既定)  .github/ 配下の設定ファイルを .claude/ に同期する
  --check      同期漏れがないかチェックのみ行う(差分があれば exit 1)
  --prune      sync 時に、同期元に存在しないファイル/ディレクトリを同期先から削除する
USAGE
}

# 引数の判定(未知の引数は誤って同期が走らないようにエラーとする)
mode="sync"
prune=false
for arg in "$@"; do
    case "$arg" in
        sync) mode="sync" ;;
        --check | check) mode="check" ;;
        --prune) prune=true ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "$mode" == "check" ]] && $prune; then
    echo "--prune は --check とは併用できない" >&2
    exit 2
fi

# 同期先にあって同期元に無いファイル/ディレクトリを削除する(--prune 指定時のみ)
# 何を消したかは必ず標準出力に列挙する。
prune_dir() {
    local src="$1" dest="$2" rel=""
    # ファイルを先に削除する
    while IFS= read -r path; do
        rel="${path#"$dest"/}"
        if [[ ! -e "$src/$rel" ]]; then
            echo "  Pruned file: $path"
            rm -f "$path"
        fi
    done < <(find "$dest" -type f)
    # 空になったディレクトリを深い順に削除する
    while IFS= read -r path; do
        rel="${path#"$dest"/}"
        if [[ "$path" != "$dest" && ! -d "$src/$rel" ]]; then
            echo "  Pruned dir:  $path"
            rmdir "$path" 2> /dev/null || true
        fi
    done < <(find "$dest" -depth -type d)
}

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
    # 孤児ファイルの削除(--prune 指定時のみ)。read-only を戻した後に実行する必要がある
    if $prune; then
        prune_dir "$src" "$dest"
    fi
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
