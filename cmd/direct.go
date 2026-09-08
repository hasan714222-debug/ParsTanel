package cmd

import (
	"context"
	"fmt"
	"time"

	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/tunnel/direct"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/sirupsen/logrus"
)

const directRestartDelay = 5 * time.Second

// runDirectTunnel keeps one direct tunnel running until ctx ends.
func runDirectTunnel(cfg *config.Config, ctx context.Context, configPath string) {
	logger := utils.NewLoggerWithFormat(directLogLevel(cfg), "")

	dc := cfg.Direct
	tunnelCfg := direct.Config{
		Role:             dc.ResolvedRole(),
		Addr:             dc.Addr,
		Token:            dc.Token,
		Transport:        dc.Transport,
		ServerName:       dc.ServerName,
		TLSCertFile:      dc.TLSCertFile,
		TLSKeyFile:       dc.TLSKeyFile,
		ACMEDomain:       dc.ACMEDomain,
		ACMEEmail:        dc.ACMEEmail,
		Ports:            dc.Ports,
		AcceptUDP:        dc.AcceptUDP,
		MaxConnections:   dc.MaxConnections,
		BandwidthMbps:    dc.BandwidthMbps,
		Sessions:         dc.Sessions,
		DialTimeout:      time.Duration(dc.DialTimeout) * time.Second,
		RetryDelay:       time.Duration(dc.RetryInterval) * time.Second,
		Keepalive:        time.Duration(dc.Keepalive) * time.Second,
		Nodelay:          dc.Nodelay,
		MSS:              dc.MSS,
		MuxVersion:       dc.MuxVersion,
		MaxFrameSize:     dc.MaxFrameSize,
		MaxReceiveBuffer: dc.MaxReceiveBuffer,
		MaxStreamBuffer:  dc.MaxStreamBuffer,
	}

	runner, role, err := newDirectRunner(tunnelCfg, logger)
	if err != nil {
		logger.Fatalf("direct tunnel configuration is not usable: %v", err)
		return
	}

	startMetrics(ctx, configPath, "direct-"+tunnelCfg.Transport, role)

	for {
		if err := runner(ctx); err != nil && ctx.Err() == nil {
			logger.Errorf("direct tunnel stopped: %v — restarting in %s", err, directRestartDelay)
		}
		if ctx.Err() != nil {
			logger.Info("shutting down the direct tunnel...")
			return
		}
		select {
		case <-ctx.Done():
			logger.Info("shutting down the direct tunnel...")
			return
		case <-time.After(directRestartDelay):
		}
	}
}

func newDirectRunner(cfg direct.Config, logger *logrus.Logger) (func(context.Context) error, string, error) {
	switch cfg.Role {
	case direct.RoleOrigin:
		origin, err := direct.NewOrigin(cfg, logger)
		if err != nil {
			return nil, "", err
		}
		return origin.Run, "kharej-origin", nil
	case direct.RoleEdge:
		edge, err := direct.NewEdge(cfg, logger)
		if err != nil {
			return nil, "", err
		}
		return edge.Run, "iran-edge", nil
	default:
		return nil, "", fmt.Errorf(
			"role %q is not one this tunnel has: write \"iran\" on the Iran server "+
				"(it exposes the ports and dials out) or \"kharej\" on the server abroad",
			cfg.Role)
	}
}

func directLogLevel(cfg *config.Config) string {
	if cfg.Server.LogLevel != "" {
		return cfg.Server.LogLevel
	}
	return cfg.Client.LogLevel
}
