// Package app holds shared constants and paths used across the parstanel
// management layer (menu, manage, schedule, optimize).
package app

import (
	"crypto/sha256"
	"encoding/binary"
)

const (
	// Version of the parstanel engine.
	Version = "v1.7.7.5"

	// RepoOwner/RepoName identify the GitHub repository used by the installer
	// and the release-based updater.
	RepoOwner = "hasan714222-debug"
	RepoName  = "ParsTanel"

	// InstallDir is where the release bundle lives on the VPS.
	InstallDir = "/root/ParsTanel"

	// BackupDir is the default folder for configuration backups.
	BackupDir = InstallDir + "/backups"

	// ConfigDir is where per-tunnel TOML configs and runtime state live.
	ConfigDir = "/etc/parstanel"

	// ServiceDir is the systemd unit directory.
	ServiceDir = "/etc/systemd/system"

	// ServicePrefix is prepended to every tunnel systemd unit.
	ServicePrefix = "parstanel-"

	// BinPath is where the parstanel binary is installed.
	BinPath = "/usr/local/bin/parstanel"

	// AutoRefreshMarker is the cron comment tag for the global auto-refresh job.
	AutoRefreshMarker = "parstanel-auto-refresh"

	// MonitorService is the systemd unit that watches the tunnels and manages
	// auto-recovery and alerts.
	MonitorService = "parstanel-monitor.service"

	// ProxyService is the systemd unit for the optional built-in SOCKS5/HTTP
	// proxy, so a node can be its own backend instead of running a separate one.
	ProxyService = "parstanel-proxy.service"

	// SocksInternalPort is the localhost port the built-in SOCKS5 proxy listens
	// on. It is reachable from a peer only when exposed over a tunnel.
	SocksInternalPort = 1080

	// InstallPathFile records where the source repo was cloned, so the updater
	// and uninstaller can find it.
	InstallPathFile = ConfigDir + "/install_path"
)

// ServiceName returns the systemd unit name for a tunnel by its short name.
func ServiceName(name string) string {
	return ServicePrefix + name + ".service"
}

// ConfigPath returns the on-disk TOML path for a tunnel by its short name.
func ConfigPath(name string) string {
	return ConfigDir + "/" + name + ".toml"
}

// SocksPortForToken derives the loopback port a tunnel's SOCKS relay uses.
func SocksPortForToken(token string) int {
	if token == "" {
		return SocksInternalPort
	}
	sum := sha256.Sum256([]byte("parstanel-socks-v1:" + token))
	return 20000 + int(binary.BigEndian.Uint32(sum[:4])%20000)
}