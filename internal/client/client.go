package client

import (
	"context"
	"time"

	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/client/transport"
	"github.com/hasan714222-debug/ParsTanel/internal/debugserver"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/handlers"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"

	"github.com/sirupsen/logrus"
)

// Client encapsulates the client configuration and state
type Client struct {
	config *config.ClientConfig
	ctx    context.Context
	cancel context.CancelFunc
	logger *logrus.Logger
}

func NewClient(cfg *config.ClientConfig, parentCtx context.Context) *Client {
	ctx, cancel := context.WithCancel(parentCtx)
	network.SetPinTCPBuffers(cfg.SOPinTCP)
	handlers.SetZeroCopy(cfg.ZeroCopy)
	return &Client{
		config: cfg,
		ctx:    ctx,
		cancel: cancel,
		logger: utils.NewLoggerWithFormat(cfg.LogLevel, cfg.LogFormat),
	}
}

// Start starts the client and begins dialing the tunnel server
func (c *Client) Start() {
	if c.config.PPROF {
		pprofStopped := make(chan struct{})
		go func() {
			defer close(pprofStopped)
			c.logger.Info("pprof listening on 127.0.0.1:6061 (loopback only)")
			if err := debugserver.Serve(c.ctx, "127.0.0.1:6061"); err != nil {
				c.logger.Errorf("pprof server stopped: %v", err)
			}
		}()
		defer func() { <-pprofStopped }()
	}

	c.logger.Infof("client with remote address %s started successfully", c.config.RemoteAddr)

	endpoints := network.NewEndpoints(c.config.RemoteAddr, c.config.FallbackAddrs...)
	if endpoints.Len() > 1 {
		c.logger.Infof("%d server endpoints configured (failover enabled)", endpoints.Len())
	}
	if c.config.LoadBalance && endpoints.Len() > 1 {
		endpoints.SetSpread(true)
		c.logger.Infof("load balancing enabled across %d endpoints", endpoints.Len())
	}
	if c.config.HealthFailover && endpoints.Len() > 1 {
		endpoints.EnableHealthSteering(c.ctx, 5*time.Second, func(m string) { c.logger.Info(m) })
		c.logger.Infof("automatic health failover enabled across %d endpoints", endpoints.Len())
	}

	outbound, err := buildOutbound(c.config)
	if err != nil {
		c.logger.Errorf("ignoring the configured outbound settings and dialling directly: %v", err)
		outbound = nil
	}
	if outbound.IsSet() {
		c.logger.Infof("reaching the tunnel server %s", outbound)
	}

	switch c.config.Transport {
	case config.TCP, config.STEALTH:
		tcpConfig := &transport.TcpConfig{
			RemoteAddr:     c.config.RemoteAddr,
			Endpoints:      endpoints,
			Nodelay:        c.config.Nodelay,
			KeepAlive:      time.Duration(c.config.Keepalive) * time.Second,
			RetryInterval:  time.Duration(c.config.RetryInterval) * time.Second,
			DialTimeOut:    time.Duration(c.config.DialTimeout) * time.Second,
			ConnPoolSize:   c.config.ConnectionPool,
			Token:          c.config.Token,
			AggressivePool: c.config.AggressivePool,
			MSS:            c.config.MSS,
			SO_RCVBUF:      c.config.SO_RCVBUF,
			SO_SNDBUF:      c.config.SO_SNDBUF,
			Outbound:       outbound,
			Stealth:        c.config.Transport == config.STEALTH,
		}
		tcpClient := transport.NewTCPClient(c.ctx, tcpConfig, c.logger)
		go tcpClient.Start()

	case config.TCPMUX:
		tcpMuxConfig := &transport.TcpMuxConfig{
			RemoteAddr:       c.config.RemoteAddr,
			Endpoints:        endpoints,
			Nodelay:          c.config.Nodelay,
			KeepAlive:        time.Duration(c.config.Keepalive) * time.Second,
			RetryInterval:    time.Duration(c.config.RetryInterval) * time.Second,
			DialTimeOut:      time.Duration(c.config.DialTimeout) * time.Second,
			ConnPoolSize:     c.config.ConnectionPool,
			Token:            c.config.Token,
			MuxVersion:       c.config.MuxVersion,
			MaxFrameSize:     c.config.MaxFrameSize,
			MaxReceiveBuffer: c.config.MaxReceiveBuffer,
			MaxStreamBuffer:  c.config.MaxStreamBuffer,
			AggressivePool:   c.config.AggressivePool,
			MSS:              c.config.MSS,
			SO_RCVBUF:        c.config.SO_RCVBUF,
			SO_SNDBUF:        c.config.SO_SNDBUF,
			Outbound:         outbound,
		}
		tcpMuxClient := transport.NewMuxClient(c.ctx, tcpMuxConfig, c.logger)
		go tcpMuxClient.Start()

	case config.KCP, config.XDI, config.PCK:
		kcp := c.config.KCPConfig.WithDefaults()
		useICMP := c.config.Transport == config.XDI
		kcpConfig := &transport.KcpConfig{
			RemoteAddr:       c.config.RemoteAddr,
			Endpoints:        endpoints,
			KeepAlive:        time.Duration(c.config.Keepalive) * time.Second,
			RetryInterval:    time.Duration(c.config.RetryInterval) * time.Second,
			DialTimeOut:      time.Duration(c.config.DialTimeout) * time.Second,
			ConnPoolSize:     c.config.ConnectionPool,
			Token:            c.config.Token,
			MuxVersion:       c.config.MuxVersion,
			MaxFrameSize:     c.config.MaxFrameSize,
			MaxReceiveBuffer: c.config.MaxReceiveBuffer,
			MaxStreamBuffer:  c.config.MaxStreamBuffer,
			AggressivePool:   c.config.AggressivePool,
			SO_RCVBUF:        c.config.SO_RCVBUF,
			SO_SNDBUF:        c.config.SO_SNDBUF,
			MTU:              kcp.MTU,
			Interval:         kcp.Interval,
			Resend:           kcp.Resend,
			NoDelay:          kcp.NoDelay,
			NoCongestion:     kcp.NoCongestion,
			SndWnd:           kcp.SndWnd,
			RcvWnd:           kcp.RcvWnd,
			AckNoDelay:       kcp.AckNoDelay,
			DataShards:       kcp.DataShards,
			ParityShards:     kcp.ParityShards,
			UseICMP:          useICMP,
			UsePck:           c.config.Transport == config.PCK,
			PckInterface:     c.config.PckInterface,
			PckGatewayMAC:    c.config.PckGatewayMAC,
			PckFlags:         c.config.PckFlags,
		}
		kcpClient := transport.NewKcpClient(c.ctx, kcpConfig, c.logger)
		go kcpClient.Start()

	case config.QUIC:
		quicConfig := &transport.QuicConfig{
			RemoteAddr:     c.config.RemoteAddr,
			Endpoints:      endpoints,
			KeepAlive:      time.Duration(c.config.Keepalive) * time.Second,
			RetryInterval:  time.Duration(c.config.RetryInterval) * time.Second,
			DialTimeOut:    time.Duration(c.config.DialTimeout) * time.Second,
			ConnPoolSize:   c.config.ConnectionPool,
			Token:          c.config.Token,
			AggressivePool: c.config.AggressivePool,
			SO_RCVBUF:      c.config.SO_RCVBUF,
			SO_SNDBUF:      c.config.SO_SNDBUF,
		}
		quicClient := transport.NewQuicClient(c.ctx, quicConfig, c.logger)
		go quicClient.Start()

	case config.WS, config.WSS:
		wsConfig := &transport.WsConfig{
			RemoteAddr:     c.config.RemoteAddr,
			Endpoints:      endpoints,
			Nodelay:        c.config.Nodelay,
			KeepAlive:      time.Duration(c.config.Keepalive) * time.Second,
			RetryInterval:  time.Duration(c.config.RetryInterval) * time.Second,
			DialTimeOut:    time.Duration(c.config.DialTimeout) * time.Second,
			ConnPoolSize:   c.config.ConnectionPool,
			Token:          c.config.Token,
			Mode:           c.config.Transport,
			SimpleAuth:     c.config.SimpleAuth,
			AggressivePool: c.config.AggressivePool,
			EdgeIP:         c.config.EdgeIP,
			MSS:            c.config.MSS,
			Outbound:       outbound,
		}
		wsClient := transport.NewWSClient(c.ctx, wsConfig, c.logger)
		go wsClient.Start()

	case config.WSMUX, config.WSSMUX:
		wsMuxConfig := &transport.WsMuxConfig{
			RemoteAddr:       c.config.RemoteAddr,
			Endpoints:        endpoints,
			Nodelay:          c.config.Nodelay,
			KeepAlive:        time.Duration(c.config.Keepalive) * time.Second,
			RetryInterval:    time.Duration(c.config.RetryInterval) * time.Second,
			DialTimeOut:      time.Duration(c.config.DialTimeout) * time.Second,
			ConnPoolSize:     c.config.ConnectionPool,
			Token:            c.config.Token,
			MuxVersion:       c.config.MuxVersion,
			MaxFrameSize:     c.config.MaxFrameSize,
			MaxReceiveBuffer: c.config.MaxReceiveBuffer,
			MaxStreamBuffer:  c.config.MaxStreamBuffer,
			Mode:             c.config.Transport,
			SimpleAuth:       c.config.SimpleAuth,
			AggressivePool:   c.config.AggressivePool,
			EdgeIP:           c.config.EdgeIP,
			MSS:              c.config.MSS,
			Outbound:         outbound,
		}
		wsMuxClient := transport.NewWSMuxClient(c.ctx, wsMuxConfig, c.logger)
		go wsMuxClient.Start()

	case config.UDP:
		udpConfig := &transport.UdpConfig{
			RemoteAddr:     c.config.RemoteAddr,
			Endpoints:      endpoints,
			RetryInterval:  time.Duration(c.config.RetryInterval) * time.Second,
			DialTimeOut:    time.Duration(c.config.DialTimeout) * time.Second,
			ConnPoolSize:   c.config.ConnectionPool,
			Token:          c.config.Token,
			AggressivePool: c.config.AggressivePool,
			SO_RCVBUF:      c.config.SO_RCVBUF,
			SO_SNDBUF:      c.config.SO_SNDBUF,
		}
		udpClient := transport.NewUDPClient(c.ctx, udpConfig, c.logger)
		go udpClient.Start()

	default:
		c.logger.Fatal("invalid transport type: ", c.config.Transport)
	}

	<-c.ctx.Done()
	c.logger.Info("all workers stopped successfully")
	c.logger.SetLevel(logrus.FatalLevel)
}

func (c *Client) Stop() {
	if c.cancel != nil {
		c.cancel()
	}
}

func buildOutbound(cfg *config.ClientConfig) (*network.Outbound, error) {
	proxy, err := network.ParseProxy(cfg.Proxy)
	if err != nil {
		return nil, err
	}
	out := &network.Outbound{
		Proxy:     proxy,
		LocalAddr: cfg.LocalAddr,
		Interface: cfg.Interface,
		Mark:      cfg.SOMark,
	}
	if !out.IsSet() {
		return nil, nil
	}
	if err := out.Validate(); err != nil {
		return nil, err
	}
	return out, nil
}
