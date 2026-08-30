#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DRY_RUN=0
CHECK_ONLY=0
REMOTE_URL=""

clean_transport_env() {
  for name in HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy GIT_SSH_COMMAND GIT_SSH_VARIANT GIT_PROXY_COMMAND; do
    unset "$name" 2>/dev/null || true
  done
  export http_proxy=""
  export https_proxy=""
  export all_proxy=""
  export HTTP_PROXY=""
  export HTTPS_PROXY=""
  export ALL_PROXY=""
  export GIT_SSH_COMMAND=""
  export GIT_SSH_VARIANT=""
  export GIT_PROXY_COMMAND=""
  export GIT_TERMINAL_PROMPT=0
  export GIT_ASKPASS=echo
}

cd "$REPO_ROOT" || {
  echo "ERROR: failed to enter repository root: $REPO_ROOT" >&2
  exit 2
}

usage() {
  cat <<'EOF'
Usage:
  bash tools/restore_github_push.sh [--dry-run] [--check-only] [--remote-url URL]

Purpose:
  Recover GitHub push capability when the current network path is blocked by stale
  DNS, stale proxy settings, or a broken outbound 443 path.

Options:
  --dry-run        Print the actions without changing the repo or environment.
  --check-only     Only diagnose the network path and exit.
  --remote-url URL Set the origin URL explicitly instead of auto-detecting it.
  -h, --help       Show this help text.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --check-only)
      CHECK_ONLY=1
      ;;
    --remote-url)
      shift
      if [[ $# -lt 1 ]]; then
        echo "ERROR: --remote-url requires a value" >&2
        exit 2
      fi
      REMOTE_URL="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

print_step() {
  echo
  echo "==> $1"
}

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] $*"
    return 0
  fi
  "$@"
}

unset_proxy_vars() {
  clean_transport_env
}

require_git_repo() {
  if ! git -C "$REPO_ROOT" rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "ERROR: The resolved repository root is not a valid Git worktree: $REPO_ROOT" >&2
    exit 2
  fi
}

probe_known_ips() {
  local ip
  for ip in 20.205.243.166 140.82.112.4 140.82.114.4 185.199.108.153 162.125.34.133; do
    if nc -vz -w 5 "$ip" 443 >/dev/null 2>&1; then
      echo "$ip"
      return 0
    fi
  done
  return 1
}

ssh_443_test() {
  local known_hosts="${TMPDIR:-/tmp}/gh_known_hosts_$$"
  ssh -T -o BatchMode=yes \
    -o ConnectTimeout=10 \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile="$known_hosts" \
    -p 443 git@ssh.github.com 2>&1
}

github_repo_from_origin() {
  local origin
  if ! origin="$(git remote get-url origin 2>/dev/null)"; then
    return 1
  fi
  printf '%s\n' "$origin"
}

convert_to_ssh443_remote() {
  local repo_url="$1"
  local repo_path=""

  if [[ "$repo_url" =~ ^git@github.com: ]]; then
    repo_path="${repo_url#git@github.com:}"
    repo_path="${repo_path%.git}"
    printf 'ssh://git@ssh.github.com:443/%s.git\n' "$repo_path"
    return 0
  fi

  if [[ "$repo_url" =~ ^https://github.com/ ]]; then
    repo_path="${repo_url#https://github.com/}"
    repo_path="${repo_path%.git}"
    printf 'ssh://git@ssh.github.com:443/%s.git\n' "$repo_path"
    return 0
  fi

  if [[ "$repo_url" =~ ^ssh://git@github.com/ ]]; then
    repo_path="${repo_url#ssh://git@github.com/}"
    repo_path="${repo_path%.git}"
    printf 'ssh://git@ssh.github.com:443/%s.git\n' "$repo_path"
    return 0
  fi

  return 1
}

main() {
  unset_proxy_vars
  require_git_repo

  print_step "Resetting proxy variables and Git transport state"
  unset_proxy_vars
  run_cmd git config --global --unset-all http.proxy 2>/dev/null || true
  run_cmd git config --global --unset-all https.proxy 2>/dev/null || true
  run_cmd git config --global --unset-all all.proxy 2>/dev/null || true
  run_cmd git config --global --unset-all core.sshCommand 2>/dev/null || true
  run_cmd git config --local --unset-all core.sshCommand 2>/dev/null || true
  echo "Environment after cleanup:"
  env | grep -Ei 'http|https|proxy|socks|all_proxy|GIT_' | sort || true

  print_step "Checking GitHub reachability"
  if probe_known_ips >/dev/null 2>&1; then
    echo "One of the known GitHub IPs is reachable on TCP 443. This is a good sign for a direct path restore."
  else
    echo "No known GitHub IP responded on TCP 443 from this environment. The path is still blocked upstream."
  fi

  print_step "Testing GitHub SSH over port 443"
  ssh_443_test || true

  print_step "Checking current remote"
  local current_origin
  current_origin="$(github_repo_from_origin || true)"
  echo "origin: ${current_origin:-<no origin> }"

  if [[ -n "$REMOTE_URL" ]]; then
    echo "Using explicit remote URL: $REMOTE_URL"
    if [[ "$DRY_RUN" -eq 0 ]]; then
      git remote set-url origin "$REMOTE_URL"
    fi
  else
    local ssh_remote=""
    if [[ -n "$current_origin" ]]; then
      ssh_remote="$(convert_to_ssh443_remote "$current_origin" || true)"
      if [[ -n "$ssh_remote" ]]; then
        echo "Recommended SSH-over-443 remote: $ssh_remote"
        if [[ "$DRY_RUN" -eq 0 ]]; then
          git remote set-url origin "$ssh_remote"
        fi
      else
        echo "Could not infer a GitHub SSH-over-443 remote from the current origin."
      fi
    fi
  fi

  if [[ "$CHECK_ONLY" -eq 1 ]]; then
    print_step "Check-only mode: skipping push attempt"
    exit 0
  fi

  print_step "Testing remote read access"
  local ssh_cmd="ssh -T -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=${TMPDIR:-/tmp}/gh_known_hosts_$$ -o ConnectTimeout=10 -p 443"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    env -u GIT_SSH_COMMAND -u GIT_SSH_VARIANT -u GIT_PROXY_COMMAND GIT_SSH_COMMAND="$ssh_cmd" git ls-remote origin HEAD
    if [[ $? -ne 0 ]]; then
      echo "ERROR: GitHub remote still not reachable from this environment." >&2
      echo "Try switching to a different outbound network path or VPN before retrying." >&2
      exit 1
    fi

    print_step "Attempting a real push"
    env -u GIT_SSH_COMMAND -u GIT_SSH_VARIANT -u GIT_PROXY_COMMAND GIT_SSH_COMMAND="$ssh_cmd" git push origin HEAD
    exit $?
  else
    echo "[DRY-RUN] env -u GIT_SSH_COMMAND -u GIT_SSH_VARIANT -u GIT_PROXY_COMMAND GIT_SSH_COMMAND='$ssh_cmd' git ls-remote origin HEAD"
    echo "[DRY-RUN] env -u GIT_SSH_COMMAND -u GIT_SSH_VARIANT -u GIT_PROXY_COMMAND GIT_SSH_COMMAND='$ssh_cmd' git push origin HEAD"
  fi
}

main "$@"
