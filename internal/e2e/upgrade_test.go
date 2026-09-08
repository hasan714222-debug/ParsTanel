package e2e

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/BurntSushi/toml"
	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/client"
	"github.com/hasan714222-debug/ParsTanel/internal/server"
)

// Upgrade safety.
//
// An update replaces the binary and restarts the services; it never rewrites a
// tunnel's config. So the new binary has to run configs written by the previous
// version, unchanged, and keep carrying traffic — otherwise updating breaks
// every tunnel on the machine at once.
//
// These tests write configs in the exact shape v1.5.0 produced (no keys added
// since), decode them the way the engine does, and run a real tunnel from them.

const v150ServerConfig = `[server]
bind_addr = "127.0.0.1:%d"
transport = "tcp"
preset = "turbo"
token = "%s"
channel_size = 4096
keepalive_period = 75
nodelay = true
heartbeat = 40
log_level = "error"
accept_udp = false
mux_con = 8
mux_version = 2
mux_framesize = 32768
mux_recievebuffer = 4194304
mux_streambuffer = 65536
proxy_protocol = false
max_connections = 0
bandwidth_mbps = 0
sniffer = false
web_port = 0
ports = ["%d=%s"]
so_rcvbuf = 8388608
so_sndbuf = 8388608
skip_optz = true
`

const v150ClientConfig = `[client]
remote_addr = "127.0.0.1:%d"
transport = "tcp"
preset = "turbo"
token = "%s"
connection_pool = 8
aggressive_pool = false
keepalive_period = 75
nodelay = true
load_balance = false
retry_interval = 1
dial_timeout = 5
log_level = "error"
mux_session = 8
mux_version = 2
mux_framesize = 32768
mux_recievebuffer = 4194304
mux_streambuffer = 65536
sniffer = false
web_port = 0
so_rcvbuf = 8388608
so_sndbuf = 8388608
skip_optz = true
`

func decodeFile(t *testing.T, path string) *config.Config {
	t.Helper()
	var cfg config.Config
	if _, err := toml.DecodeFile(path, &cfg); err != nil {
		t.Fatalf("a config written by the previous version failed to decode: %v", err)
	}
	return &cfg
}

func TestPreviousVersionConfigStillDecodes(t *testing.T) {
	dir := t.TempDir()
	srvPath := filepath.Join(dir, "srv.toml")
	body := fmt.Sprintf(v150ServerConfig, 1234, "tok-0123456789abcdefghijklmno", 8443, "127.0.0.1:9000")
	if err := os.WriteFile(srvPath, []byte(body), 0600); err != nil {
		t.Fatal(err)
	}
	cfg := decodeFile(t, srvPath)

	if cfg.Server.Token != "tok-0123456789abcdefghijklmno" {
		t.Fatalf("token lost: %q", cfg.Server.Token)
	}
	if cfg.Server.SO_RCVBUF != 8388608 || cfg.Server.SO_SNDBUF != 8388608 {
		t.Fatalf("socket buffers lost: %d/%d", cfg.Server.SO_RCVBUF, cfg.Server.SO_SNDBUF)
	}
	if cfg.Server.MuxCon != 8 || cfg.Server.ChannelSize != 4096 {
		t.Fatalf("mux/channel settings lost: %+v", cfg.Server)
	}
	if len(cfg.Server.Ports) != 1 {
		t.Fatalf("port mapping lost: %v", cfg.Server.Ports)
	}

	if cfg.Server.SOPinTCP {
		t.Fatal("so_pin_tcp must default to false on a config that predates it")
	}
}

func TestPreviousVersionConfigStillCarriesTraffic(t *testing.T) {
	backend := startEchoBackend(t)
	tunnelPort := freePort(t)
	entryPort := freePort(t)
	token := "upgrade-token-0123456789abcdef"

	dir := t.TempDir()
	srvPath := filepath.Join(dir, "srv.toml")
	cliPath := filepath.Join(dir, "cli.toml")
	if err := os.WriteFile(srvPath,
		fmt.Appendf(nil, v150ServerConfig, tunnelPort, token, entryPort, backend.addr), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(cliPath,
		fmt.Appendf(nil, v150ClientConfig, tunnelPort, token), 0600); err != nil {
		t.Fatal(err)
	}

	srvCfg := &decodeFile(t, srvPath).Server
	cliCfg := &decodeFile(t, cliPath).Client

	ctx, cancel := context.WithCancel(context.Background())
	var wg sync.WaitGroup
	t.Cleanup(func() { cancel(); wg.Wait() })

	srv := server.NewServer(srvCfg, ctx)
	wg.Add(1)
	go func() { defer wg.Done(); srv.Start() }()
	time.Sleep(300 * time.Millisecond)
	cli := client.NewClient(cliCfg, ctx)
	wg.Add(1)
	go func() { defer wg.Done(); cli.Start() }()

	entry := fmt.Sprintf("127.0.0.1:%d", entryPort)
	deadline := time.Now().Add(tunnelReadyTimeout)
	var lastErr error
	for time.Now().Before(deadline) {
		if lastErr = poolRoundTrip(entry, []byte("upgraded-and-still-working")); lastErr == nil {
			return
		}
		time.Sleep(250 * time.Millisecond)
	}
	t.Fatalf("a tunnel from the previous version's config stopped carrying traffic: %v", lastErr)
}