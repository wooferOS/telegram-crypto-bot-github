#!/usr/bin/env bash
set -euo pipefail

PREFIX=${PREFIX:-/usr/local/bin}

install_wrapper() {
    local name=$1
    shift
    local content="$*"
    local target="$PREFIX/$name"
    echo "Installing $target"
    mkdir -p "$(dirname "$target")"
    cat <<'SCRIPT' > "$target"
#!/usr/bin/env bash
set -euo pipefail
SCRIPT
    cat <<SCRIPT >> "$target"
$content
SCRIPT
    chmod +x "$target"
}

install_wrapper cspot 'python3 -m src.cli now "$@" --wallet=SPOT'
install_wrapper cfund 'python3 -m src.cli now "$@" --wallet=FUNDING'
install_wrapper cqspot 'python3 -m src.cli quote "$@" --wallet=SPOT'
install_wrapper cqfund 'python3 -m src.cli quote "$@" --wallet=FUNDING'
install_wrapper cinfo 'python3 -m src.cli info "$@"'
install_wrapper cstat 'python3 -m src.cli status "$@"'
install_wrapper ctrades 'python3 -m src.cli trades "$@"'

install_wrapper auto-asia 'phase="${1:-analyze}"
shift || true
flock -n /tmp/asia.lock python3 -m src.cli run --region=asia --phase="$phase" "$@"'

install_wrapper auto-us 'phase="${1:-analyze}"
shift || true
flock -n /tmp/us.lock python3 -m src.cli run --region=us --phase="$phase" "$@"'

echo "Done"
