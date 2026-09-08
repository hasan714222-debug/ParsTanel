package cmd

import (
	"context"
	"path/filepath"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/client"
	"github.com/hasan714222-debug/ParsTanel/internal/metrics"
	"github.com/hasan714222-debug/ParsTanel/internal/server"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/handlers"
)

var (
	logger = utils.NewLogger("info")
)

// tunnelNameFromPath derives a tunnel's name from its config path, which is
// how the rest of the tool identifies it.
func tunnelNameFromPath(configPath string) string {
	base := filepath.Base(configPath)
	return strings.TrimSuffix(base, filepath.Ext(base))
}

// startMetrics records what the tunnel carries so the CLI can show it later.
// It is best-effort: a tunnel must never fail because diagnostics could not be
// written.
func startMetrics(ctx context.Context, configPath, transport, role string) {
	startMetricsWithTraffic(ctx, configPath, transport, role, nil, nil)
}

// startMetricsWithTraffic is the same, for an engine that counts its own
// traffic rather than reporting it through metrics.AddBytes.
func startMetricsWithTraffic(
	ctx context.Context,
	configPath, transport, role string,
	bytesIn, bytesOut func() uint64,
) {
	name := tunnelNameFromPath(configPath)
	if name == "" {
		return
	}
	c := metrics.NewCollector(filepath.Dir(configPath), name, transport, role, bytesIn, bytesOut)
	go func() {
		done := make(chan struct{})
		go func() { <-ctx.Done(); close(done) }()
		_ = c.Write() // an immediate first reading, so the file exists right away
		c.Run(done, 30*time.Second)
	}()
}

// Run keeps one tunnel running from a configuration file, restarting it in
// place whenever the file changes.
func Run(configPath string, ctx context.Context) {
	cfg, err := loadConfig(configPath)
	if err != nil {
		logger.Fatalf("failed to load configuration: %v", err)
	}
	applyDefaults(cfg)

	tuned := false

	for {
		running := *cfg

		applyTuning := !tuned
		tuned = true

		runCtx, cancel := context.WithCancel(ctx)
		done := make(chan struct{})
		go func() {
			defer close(done)
			runEngine(&running, runCtx, configPath, applyTuning)
		}()

		next := awaitConfigChange(ctx, configPath, cfg)
		cancel()
		<-done

		if next == nil {
			return // ctx ended: shutting down, not reloading
		}

		logger.Info("the configuration file changed; restarting the tunnel with it")
		waitForPorts(ctx, portsInUse(cfg))
		cfg = next
	}
}

// runEngine runs one tunnel until ctx ends.
func runEngine(cfg *config.Config, ctx context.Context, configPath string, applyTuning bool) {
	if cfg.L3.Enabled() {
		runL3Tunnel(cfg, ctx, configPath)
		return
	}
	if cfg.Direct.Enabled() {
		runDirectTunnel(cfg, ctx, configPath)
		return
	}

	configType := ""
	if cfg.Server.BindAddr != "" {
		configType = "server"
	} else if cfg.Client.RemoteAddr != "" {
		configType = "client"
	} else {
		logger.Fatalf("neither server nor client configuration is properly set.")
	}

	switch configType {
	case "server":
		if applyTuning && !cfg.Server.SkipOptz {
			ApplyTCPTuning()
		}

		startMetrics(ctx, configPath, string(cfg.Server.Transport), "server")

		srv := server.NewServer(&cfg.Server, ctx)
		reportZeroCopy(ctx)
		srv.Start()
		srv.Stop()
		logger.Println("shutting down server...")
	case "client":
		if applyTuning && !cfg.Client.SkipOptz {
			ApplyTCPTuning()
		}

		startMetrics(ctx, configPath, string(cfg.Client.Transport), "client")

		clnt := client.NewClient(&cfg.Client, ctx)
		reportZeroCopy(ctx)
		clnt.Start()
		clnt.Stop()
		logger.Println("shutting down client...")

	default:
		logger.Fatalf("neither server nor client configuration is properly set.")
	}
}

// loadConfig loads and parses the TOML configuration file.
func loadConfig(configPath string) (*config.Config, error) {
	var cfg config.Config
	if _, err := toml.DecodeFile(configPath, &cfg); err != nil {
		return &cfg, err
	}
	return &cfg, nil
}

// reportZeroCopy logs whether the kernel zero-copy forwarding path is in effect.
func reportZeroCopy(ctx context.Context) {
	if !handlers.ZeroCopy() {
		return
	}
	logger.Infof("zero-copy forwarding is enabled (experimental; plain tcp transport on Linux only) — %s", handlers.RelaySummary())

	go func() {
		t := time.NewTicker(5 * time.Minute)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				logger.Infof("zero-copy forwarding: %s", handlers.RelaySummary())
			}
		}
	}()
}