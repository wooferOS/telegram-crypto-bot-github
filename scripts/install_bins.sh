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
    {
        printf '#!/usr/bin/env bash\n'
        printf 'set -euo pipefail\n'
        printf '%s\n' "$content"
    } >"$target"
    chmod +x "$target"
}

install_wrapper cspot 'python3 -m src.cli now "$@" --wallet=SPOT'
install_wrapper cfund 'python3 -m src.cli now "$@" --wallet=FUNDING'
install_wrapper cqspot 'python3 -m src.cli quote "$@" --wallet=SPOT'
install_wrapper cqfund 'python3 -m src.cli quote "$@" --wallet=FUNDING'
install_wrapper auto-asia 'phase="${1:?phase required}"; shift || true; python3 -m src.app --region asia --phase="$phase" "$@"'
install_wrapper auto-us 'phase="${1:?phase required}"; shift || true; python3 -m src.app --region us --phase="$phase" "$@"'

echo "Done"
