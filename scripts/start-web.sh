#!/usr/bin/env bash
# Compatible with macOS's built-in Bash 3.2 and Linux Bash.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/start-web.sh [start|status|stop|restart] [options]

Install dependencies, build the frontend, and start the local Web workbench.

Options:
  --provider fake|compatible  Model provider (default: fake)
  --workspace PATH           Existing workspace (default: project root)
  --database PATH            Database outside the workspace (default: ~/.pi-agent/web.sqlite)
  --port NUMBER              Local HTTP port (default: 8766)
  --force                    Force stop/restart after graceful shutdown timeout
  --enable-file-mutations    Enable file write/edit (default: enabled)
  --no-enable-file-mutations Disable file write/edit on this server
  --require-approval        Require write/edit/command approval (default: enabled)
  --no-require-approval     Execute selected tools without human approval
  --allow-executable PATH   Replace default shell allowlist (repeatable)
  --disable-command         Disable command on this server
  -h, --help                 Show this help

Relative paths are resolved from the project root.
With --provider compatible, the project's .env is loaded if present.
Requires uv and Node.js/npm; see README.md for supported versions.
EOF
}

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

provider=fake
action=start
force=false
coding_arguments=()
if (( $# > 0 )); then
    case "$1" in
        start|status|stop|restart) action=$1; shift ;;
    esac
fi
workspace=.
database=
port=8766

while (( $# > 0 )); do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --force) force=true; shift ;;
        --enable-file-mutations|--no-enable-file-mutations|--require-approval|--no-require-approval|--disable-command)
            coding_arguments+=("$1"); shift ;;
        --allow-executable)
            (( $# >= 2 )) || fail "Missing value for $1."
            [[ -n "$2" && "$2" != --* ]] || fail "Missing value for $1."
            coding_arguments+=(--allow-executable "$2"); shift 2 ;;
        --provider|--workspace|--database|--port)
            (( $# >= 2 )) || fail "Missing value for $1."
            [[ -n "$2" && "$2" != --* ]] || fail "Missing value for $1."
            case "$1" in
                --provider) provider=$2 ;;
                --workspace) workspace=$2 ;;
                --database) database=$2 ;;
                --port) port=$2 ;;
            esac
            shift 2
            ;;
        *) fail "Unknown option: $1. Use --help for usage." ;;
    esac
done

case "$provider" in
    fake|compatible) ;;
    *) fail "Provider must be fake or compatible." ;;
esac
[[ "$port" =~ ^[0-9]{1,5}$ ]] || fail "Port must be an integer from 1 to 65535."
(( 10#$port >= 1 && 10#$port <= 65535 )) || fail "Port must be from 1 to 65535."
port=$((10#$port))

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$project_root"
command_names=(uv)
if [[ "$action" == start || "$action" == restart ]]; then
    [[ -d "$workspace" ]] || fail "Workspace must be an existing directory: $workspace"
    command_names+=(node npm)
fi
for command_name in "${command_names[@]}"; do
    command -v "$command_name" >/dev/null 2>&1 || fail "Required command not found: $command_name"
done

if [[ "$action" == start || "$action" == restart ]]; then
uv sync --extra web
(
    cd -- "$project_root/web-ui"
    if [[ ! -d node_modules ]]; then
        npm ci --no-fund --no-audit
    fi
    npm run build
)
fi

run_arguments=(run --no-sync --extra web)
if [[ "$provider" == compatible && -f .env ]]; then
    run_arguments+=(--env-file .env)
fi
run_arguments+=(pi-agent-web "$action" --provider "$provider" --workspace "$workspace" --port "$port")
if (( ${#coding_arguments[@]} > 0 )); then run_arguments+=("${coding_arguments[@]}"); fi
if [[ "$force" == true ]]; then run_arguments+=(--force); fi
if [[ -n "$database" ]]; then
    run_arguments+=(--database "$database")
fi
exec uv "${run_arguments[@]}"
