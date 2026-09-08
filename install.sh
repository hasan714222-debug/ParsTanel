--- START OF FILE install.sh ---
#!/usr/bin/env bash
set -e

REPO_OWNER="hasan714222-debug"
REPO_NAME="ParsTanel"
BIN_NAME="parstanel"
INSTALL_BIN="/usr/local/bin/${BIN_NAME}"
CONFIG_DIR="/etc/${BIN_NAME}"
INSTALL_DIR="/root/${REPO_NAME}"

echo "======================================================="
echo "             ParsTanel Installation Script"
echo "======================================================="

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: This script must be run as root." >&2
    exit 1
fi

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)  ASSET_ARCH="amd64" ;;
    aarch64|arm64) ASSET_ARCH="arm64" ;;
    *)
        echo "Error: Unsupported architecture: ${ARCH}" >&2
        exit 1
        ;;
esac

echo "System architecture: ${ARCH} (${ASSET_ARCH})"

CURL_AUTH=()
if [ -n "${GH_TOKEN}" ]; then
    CURL_AUTH=(-H "Authorization: token ${GH_TOKEN}")
fi

install_binary() {
    local bin_source="$1"
    install -m 0755 "${bin_source}" "${INSTALL_BIN}"
    mkdir -p "${CONFIG_DIR}" "${INSTALL_DIR}/backups"
    echo "${INSTALL_DIR}" > "${CONFIG_DIR}/install_path"
    echo "ParsTanel installed successfully to ${INSTALL_BIN}."
}

# 1. Check for local archive in the current directory or /root
LOCAL_TAR="parstanel_linux_${ASSET_ARCH}.tar.gz"
if [ -f "${LOCAL_TAR}" ] || [ -f "/root/${LOCAL_TAR}" ]; then
    TARGET_TAR="${LOCAL_TAR}"
    [ ! -f "${TARGET_TAR}" ] && TARGET_TAR="/root/${LOCAL_TAR}"
    echo "Found local release archive: ${TARGET_TAR}"
    TMP_DIR="$(mktemp -d)"
    tar -xzf "${TARGET_TAR}" -C "${TMP_DIR}"
    install_binary "${TMP_DIR}/${BIN_NAME}"
    rm -rf "${TMP_DIR}"
    exec "${INSTALL_BIN}"
fi

# 2. Try downloading prebuilt release binary from GitHub Releases
echo "Downloading latest release asset: ${LOCAL_TAR}..."
LATEST_TAG="$(curl -fsSL "${CURL_AUTH[@]}" "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest" | grep -Po '"tag_name":\s*"\K[^"]*' || true)"

DOWNLOAD_SUCCESS=false
if [ -n "${LATEST_TAG}" ]; then
    DOWNLOAD_URL="https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/download/${LATEST_TAG}/${LOCAL_TAR}"
    TMP_TAR="/tmp/${LOCAL_TAR}"
    if curl -fsSL "${CURL_AUTH[@]}" -o "${TMP_TAR}" "${DOWNLOAD_URL}"; then
        TMP_DIR="$(mktemp -d)"
        tar -xzf "${TMP_TAR}" -C "${TMP_DIR}"
        install_binary "${TMP_DIR}/${BIN_NAME}"
        rm -rf "${TMP_DIR}" "${TMP_TAR}"
        DOWNLOAD_SUCCESS=true
        exec "${INSTALL_BIN}"
    fi
fi

if [ "${DOWNLOAD_SUCCESS}" = false ]; then
    echo "Direct release download failed or no releases found."
    echo "Falling back to build from source..."

    # Check if Go is installed
    if ! command -v go >/dev/null 2>&1; then
        echo "Go compiler not found. Attempting to install Go..."
        if command -v apt-get >/dev/null 2>&1; then
            apt-get update -y && apt-get install -y golang-go git make curl
        elif command -v yum >/dev/null 2>&1; then
            yum install -y golang git make curl
        else
            echo "Error: Package manager not recognized. Please install Go (1.24+) manually." >&2
            exit 1
        fi
    fi

    TMP_SRC="$(mktemp -d)"
    echo "Cloning repository..."
    if [ -n "${GH_TOKEN}" ]; then
        git clone "https://${GH_TOKEN}@github.com/${REPO_OWNER}/${REPO_NAME}.git" "${TMP_SRC}"
    else
        git clone "https://github.com/${REPO_OWNER}/${REPO_NAME}.git" "${TMP_SRC}"
    fi

    cd "${TMP_SRC}"
    echo "Compiling ParsTanel..."
    CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o "${BIN_NAME}" .
    install_binary "${TMP_SRC}/${BIN_NAME}"
    rm -rf "${TMP_SRC}"
    exec "${INSTALL_BIN}"
fi
--- END OF FILE ---