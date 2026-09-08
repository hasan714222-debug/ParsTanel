#!/usr/bin/env bash

# ParsTanel installer script
# Repository: https://github.com/hasan714222-debug/ParsTanel

set -e

RED='\033[31m'
GREEN='\033[32m'
YELLOW='\033[33m'
WHITE='\033[37m'
GRAY='\033[90m'
BOLD='\033[1m'
RESET='\033[0m'

REPO_OWNER="hasan714222-debug"
REPO_NAME="ParsTanel"
BIN_NAME="parstanel"
INSTALL_DIR="/root/ParsTanel"
CONFIG_DIR="/etc/parstanel"
BACKUP_DIR="${INSTALL_DIR}/backups"
BIN_PATH="/usr/local/bin/${BIN_NAME}"

info() { echo -e "${WHITE}$1${RESET}"; }
success() { echo -e "${GREEN}${BOLD}$1${RESET}"; }
warn() { echo -e "${YELLOW}$1${RESET}"; }
error() { echo -e "${RED}${BOLD}$1${RESET}"; }

if [ "$EUID" -ne 0 ]; then
    error "Error: This script must be run as root. Run with sudo."
    exit 1
fi

ARCH="$(uname -m)"
case "${ARCH}" in
    x86_64)
        TARGET_ARCH="amd64"
        ;;
    aarch64|arm64)
        TARGET_ARCH="arm64"
        ;;
    *)
        error "Unsupported architecture: ${ARCH}. Only x86_64 and aarch64 are supported."
        exit 1
        ;;
esac

ASSET_NAME="parstanel_linux_${TARGET_ARCH}.tar.gz"

info "======================================================="
info "             ParsTanel Installation Script"
info "======================================================="
info "System architecture: ${ARCH} (${TARGET_ARCH})"

mkdir -p "${INSTALL_DIR}"
mkdir -p "${CONFIG_DIR}"
mkdir -p "${BACKUP_DIR}"

WORKDIR="$(pwd)"
LOCAL_ARCHIVE=""

# Check if archive exists in current working directory (Offline install mode)
if [ -f "${WORKDIR}/${ASSET_NAME}" ]; then
    info "Found local release archive: ${WORKDIR}/${ASSET_NAME}"
    LOCAL_ARCHIVE="${WORKDIR}/${ASSET_NAME}"
fi

verify_sha256() {
    local file_path="$1"
    local checksum_file="$2"
    if [ ! -f "${checksum_file}" ]; then
        warn "Warning: Checksum file not found. Skipping checksum verification."
        return 0
    fi
    info "Verifying SHA256 checksum..."
    local expected_hash
    expected_hash=$(grep "${ASSET_NAME}" "${checksum_file}" | awk '{print $1}')
    if [ -z "${expected_hash}" ]; then
        warn "Warning: Archive ${ASSET_NAME} not listed in ${checksum_file}."
        return 0
    fi

    local actual_hash
    actual_hash=$(sha256sum "${file_path}" | awk '{print $1}')
    if [ "${expected_hash}" != "${actual_hash}" ]; then
        error "Checksum verification failed!"
        error "Expected: ${expected_hash}"
        error "Actual:   ${actual_hash}"
        return 1
    fi
    success "Checksum verified successfully."
    return 0
}

download_release() {
    local download_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/latest/download/${ASSET_NAME}"
    local sums_url="https://github.com/${REPO_OWNER}/${REPO_NAME}/releases/latest/download/SHA256SUMS"
    local target_archive="${INSTALL_DIR}/${ASSET_NAME}"
    local target_sums="${INSTALL_DIR}/SHA256SUMS"

    info "Downloading latest release asset: ${ASSET_NAME}..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "${target_archive}" "${download_url}" || return 1
        curl -fsSL -o "${target_sums}" "${sums_url}" || true
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "${target_archive}" "${download_url}" || return 1
        wget -q -O "${target_sums}" "${sums_url}" || true
    else
        error "Neither curl nor wget found. Please install curl or wget."
        return 1
    fi

    if [ -f "${target_sums}" ]; then
        verify_sha256 "${target_archive}" "${target_sums}" || return 1
    fi

    LOCAL_ARCHIVE="${target_archive}"
    return 0
}

build_from_source() {
    info "Attempting build from source..."
    if ! command -v go >/dev/null 2>&1; then
        error "Go compiler not found. Please install Go 1.24+ or download the prebuilt binary."
        return 1
    fi

    local src_dir="${WORKDIR}"
    if [ ! -f "${src_dir}/main.go" ]; then
        error "Source code not found in current directory (${src_dir})."
        return 1
    fi

    info "Building ParsTanel binary with Go..."
    CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o "${INSTALL_DIR}/${BIN_NAME}" "${src_dir}"
    chmod 0755 "${INSTALL_DIR}/${BIN_NAME}"
    cp -f "${INSTALL_DIR}/${BIN_NAME}" "${BIN_PATH}"
    return 0
}

# 1. Try local archive if available
if [ -n "${LOCAL_ARCHIVE}" ]; then
    info "Installing from local file..."
    if [ -f "${WORKDIR}/SHA256SUMS" ]; then
        verify_sha256 "${LOCAL_ARCHIVE}" "${WORKDIR}/SHA256SUMS"
    fi
    tar -xzf "${LOCAL_ARCHIVE}" -C "${INSTALL_DIR}"
    if [ -f "${INSTALL_DIR}/${BIN_NAME}" ]; then
        install -m 0755 "${INSTALL_DIR}/${BIN_NAME}" "${BIN_PATH}"
    else
        error "Binary ${BIN_NAME} was not found inside the archive."
        exit 1
    fi
# 2. Try download from GitHub
elif download_release; then
    tar -xzf "${LOCAL_ARCHIVE}" -C "${INSTALL_DIR}"
    if [ -f "${INSTALL_DIR}/${BIN_NAME}" ]; then
        install -m 0755 "${INSTALL_DIR}/${BIN_NAME}" "${BIN_PATH}"
    else
        error "Binary ${BIN_NAME} was not found inside the archive."
        exit 1
    fi
# 3. Fallback to build from source
else
    warn "Direct download failed. Falling back to build from source..."
    build_from_source
fi

# Record install path for uninstaller & self-updates
echo "${INSTALL_DIR}" > "${CONFIG_DIR}/install_path"

success "======================================================="
success "        ParsTanel installed successfully!"
success "======================================================="
info "Run command: sudo parstanel"
echo ""

# Launch CLI if standard input is a terminal
if [ -t 0 ]; then
    exec "${BIN_PATH}"
fi