package cmd

import (
	"context"
	"sync"
	"time"

	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/tunnel/l3"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"
)

const l3RestartDelay = 5 * time.Second

// runL3Tunnel keeps one layer-3 tunnel running until ctx ends.
func runL3Tunnel(cfg *config.Config, ctx context.Context, configPath string) {
	logger := utils.NewLoggerWithFormat(l3LogLevel(cfg), "")

	tunnelCfg := l3.Config{
		Mode:           cfg.L3.Mode,
		Addr:           cfg.L3.Addr,
		Token:          cfg.L3.Token,
		Carrier:        cfg.L3.Carrier,
		Encap:          cfg.L3.Encap,
		GREKey:         cfg.L3.GREKey,
		Iface:          cfg.L3.Iface,
		LocalIP:        cfg.L3.LocalIP,
		PeerIP:         cfg.L3.PeerIP,
		MTU:            cfg.L3.MTU,
		SockBuf:        cfg.L3.SockBuf,
		TxQueueLen:     cfg.L3.TxQueueLen,
		Qdisc:          cfg.L3.Qdisc,
		MSSClamp:       cfg.L3.MSSClamp,
		AutoMTU:        cfg.L3.AutoMTUEnabled(),
		Ports:          cfg.L3.Ports,
		AcceptUDP:      cfg.L3.AcceptUDP,
		MaxConnections: cfg.L3.MaxConnections,
		BandwidthMbps:  cfg.L3.BandwidthMbps,
		FEC:            l3.FECConfig{Data: cfg.L3.FECData, Parity: cfg.L3.FECParity},
		Multipath:      l3.MultipathConfig{Paths: cfg.L3.Paths},
		Spoof:          cfg.L3.SpoofConfig,
		SNIDomain:      cfg.L3.SNIDomain,
		Pck: network.PcapCarrier{
			Interface:  cfg.L3.PckInterface,
			GatewayMAC: cfg.L3.PckGatewayMAC,
		},
	}

	if len(cfg.L3.PckFlags) > 0 {
		flags, err := network.ParseTCPFlagList(cfg.L3.PckFlags)
		if err != nil {
			logger.Fatalf("layer-3 tunnel: pck_flags: %v", err)
			return
		}
		tunnelCfg.Pck.Flags = flags
	}

	tunnel, err := l3.New(tunnelCfg, logger)
	if err != nil {
		logger.Fatalf("layer-3 tunnel configuration is not usable: %v", err)
		return
	}

	forwarder, err := l3.NewForwarder(tunnelCfg, logger)
	if err != nil {
		logger.Fatalf("layer-3 tunnel port mappings are not usable: %v", err)
		return
	}

	startMetricsWithTraffic(ctx, configPath, "l3-"+tunnelCfg.Carrier, l3Role(tunnelCfg.Mode),
		func() uint64 { return tunnel.Stats().BytesIn },
		func() uint64 { return tunnel.Stats().BytesOut },
	)

	var forwarding sync.WaitGroup
	if forwarder != nil {
		forwarding.Add(1)
		go func() {
			defer forwarding.Done()
			if err := forwarder.Run(ctx); err != nil {
				logger.Errorf("layer-3 port forwarding stopped: %v", err)
			}
		}()
	}
	defer forwarding.Wait()

	for {
		if err := tunnel.Run(ctx); err != nil && ctx.Err() == nil {
			logger.Errorf("layer-3 tunnel stopped: %v — restarting in %s", err, l3RestartDelay)
		}
		if ctx.Err() != nil {
			logger.Info("shutting down the layer-3 tunnel...")
			return
		}
		select {
		case <-ctx.Done():
			logger.Info("shutting down the layer-3 tunnel...")
			return
		case <-time.After(l3RestartDelay):
		}
	}
}

func l3LogLevel(cfg *config.Config) string {
	if cfg.Server.LogLevel != "" {
		return cfg.Server.LogLevel
	}
	return cfg.Client.LogLevel
}

func l3Role(mode string) string {
	if mode == l3.ModeDial {
		return "iran-edge"
	}
	return "kharej-origin"
}
