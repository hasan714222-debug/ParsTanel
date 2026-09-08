package server

import (
	"context"
	"time"

	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/debugserver"
	"github.com/hasan714222-debug/ParsTanel/internal/server/transport"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/handlers"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"

	"github.com/sirupsen/logrus"
)

const acmeCacheDir = app.ConfigDir + "/acme"

type Server struct {
	config *config.ServerConfig
	ctx    context.Context
	cancel context.CancelFunc
	logger *logrus.Logger
}

func NewServer(cfg *config.ServerConfig, parentCtx context.Context) *Server {
	ctx, cancel := context.WithCancel(parentCtx)
	network.SetPinTCPBuffers(cfg.SOPinTCP)
	handlers.SetZeroCopy(cfg.ZeroCopy)
	return &Server{
		config: cfg,
		ctx:    ctx,
		cancel: cancel,
		logger: utils.NewLoggerWithFormat(cfg.LogLevel, cfg.LogFormat),
	}
}

func (s *Server) Start() {
	if s.config.PPROF {
		pprofStopped := make(chan struct{})
		go func() {
			defer close(pprofStopped)
			s.logger.Info("pprof listening on 127.0.0.1:6060 (loopback only)")
			if err := debugserver.Serve(s.ctx, "127.0.0.1:6060"); err != nil {
				s.logger.Errorf("pprof server stopped: %v", err)
			}
		}()
		defer func() { <-pprofStopped }()
	}

	switch s.config.Transport {
	case config.TCP, config.STEALTH:
		tcpConfig := &transport.TcpConfig{
			BindAddr:       s.config.BindAddr,
			Nodelay:        s.config.Nodelay,
			KeepAlive:      time.Duration(s.config.Keepalive) * time.Second,
			Heartbeat:      time.Duration(s.config.Heartbeat) * time.Second,
			Token:          s.config.Token,
			ChannelSize:    s.config.ChannelSize,
			Ports:          s.config.Ports,
			AcceptUDP:      s.config.ForwardsUDP(),
			MSS:            s.config.MSS,
			SO_RCVBUF:      s.config.SO_RCVBUF,
			SO_SNDBUF:      s.config.SO_SNDBUF,
			ProxyProtocol:  s.config.ProxyProtocol,
			MaxConnections: s.config.MaxConnections,
			BandwidthMbps:  s.config.BandwidthMbps,
			Stealth:        s.config.Transport == config.STEALTH,
		}
		tcpServer := transport.NewTCPServer(s.ctx, tcpConfig, s.logger)
		go tcpServer.Start()

	case config.KCP, config.XDI, config.PCK:
		kcp := s.config.KCPConfig.WithDefaults()
		useICMP := s.config.Transport == config.XDI
		kcpConfig := &transport.KcpConfig{
			AcceptUDP:        s.config.ForwardsUDP(),
			BindAddr:         s.config.BindAddr,
			Heartbeat:        time.Duration(s.config.Heartbeat) * time.Second,
			Token:            s.config.Token,
			ChannelSize:      s.config.ChannelSize,
			Ports:            s.config.Ports,
			MuxCon:           s.config.MuxCon,
			MuxVersion:       s.config.MuxVersion,
			MaxFrameSize:     s.config.MaxFrameSize,
			MaxReceiveBuffer: s.config.MaxReceiveBuffer,
			MaxStreamBuffer:  s.config.MaxStreamBuffer,
			SO_RCVBUF:        s.config.SO_RCVBUF,
			SO_SNDBUF:        s.config.SO_SNDBUF,
			ProxyProtocol:    s.config.ProxyProtocol,
			MaxConnections:   s.config.MaxConnections,
			BandwidthMbps:    s.config.BandwidthMbps,
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
			UsePck:           s.config.Transport == config.PCK,
			PckInterface:     s.config.PckInterface,
			PckGatewayMAC:    s.config.PckGatewayMAC,
			PckFlags:         s.config.PckFlags,
		}
		kcpServer := transport.NewKcpServer(s.ctx, kcpConfig, s.logger)
		go kcpServer.Start()

	case config.QUIC:
		quicConfig := &transport.QuicConfig{
			AcceptUDP:      s.config.ForwardsUDP(),
			BindAddr:       s.config.BindAddr,
			Heartbeat:      time.Duration(s.config.Heartbeat) * time.Second,
			KeepAlive:      time.Duration(s.config.Keepalive) * time.Second,
			Token:          s.config.Token,
			ChannelSize:    s.config.ChannelSize,
			Ports:          s.config.Ports,
			SO_RCVBUF:      s.config.SO_RCVBUF,
			SO_SNDBUF:      s.config.SO_SNDBUF,
			ProxyProtocol:  s.config.ProxyProtocol,
			MaxConnections: s.config.MaxConnections,
			BandwidthMbps:  s.config.BandwidthMbps,
		}
		quicServer := transport.NewQuicServer(s.ctx, quicConfig, s.logger)
		go quicServer.Start()

	case config.TCPMUX:
		tcpMuxConfig := &transport.TcpMuxConfig{
			AcceptUDP:        s.config.ForwardsUDP(),
			BindAddr:         s.config.BindAddr,
			Nodelay:          s.config.Nodelay,
			KeepAlive:        time.Duration(s.config.Keepalive) * time.Second,
			Heartbeat:        time.Duration(s.config.Heartbeat) * time.Second,
			Token:            s.config.Token,
			ChannelSize:      s.config.ChannelSize,
			Ports:            s.config.Ports,
			MuxCon:           s.config.MuxCon,
			MuxVersion:       s.config.MuxVersion,
			MaxFrameSize:     s.config.MaxFrameSize,
			MaxReceiveBuffer: s.config.MaxReceiveBuffer,
			MaxStreamBuffer:  s.config.MaxStreamBuffer,
			MSS:              s.config.MSS,
			SO_RCVBUF:        s.config.SO_RCVBUF,
			SO_SNDBUF:        s.config.SO_SNDBUF,
			ProxyProtocol:    s.config.ProxyProtocol,
			MaxConnections:   s.config.MaxConnections,
			BandwidthMbps:    s.config.BandwidthMbps,
		}
		tcpMuxServer := transport.NewTcpMuxServer(s.ctx, tcpMuxConfig, s.logger)
		go tcpMuxServer.Start()

	case config.WS, config.WSS:
		wsConfig := &transport.WsConfig{
			AcceptUDP:      s.config.ForwardsUDP(),
			BindAddr:       s.config.BindAddr,
			Nodelay:        s.config.Nodelay,
			KeepAlive:      time.Duration(s.config.Keepalive) * time.Second,
			Heartbeat:      time.Duration(s.config.Heartbeat) * time.Second,
			Token:          s.config.Token,
			ChannelSize:    s.config.ChannelSize,
			Ports:          s.config.Ports,
			Mode:           s.config.Transport,
			SimpleAuth:     s.config.SimpleAuth,
			TLSCertFile:    s.config.TLSCertFile,
			ACMEDomain:     s.config.ACMEDomain,
			ACMEEmail:      s.config.ACMEEmail,
			ACMECacheDir:   acmeCacheDir,
			TLSKeyFile:     s.config.TLSKeyFile,
			MSS:            s.config.MSS,
			MaxConnections: s.config.MaxConnections,
			BandwidthMbps:  s.config.BandwidthMbps,
		}
		wsServer := transport.NewWSServer(s.ctx, wsConfig, s.logger)
		go wsServer.Start()

	case config.WSMUX, config.WSSMUX:
		wsMuxConfig := &transport.WsMuxConfig{
			AcceptUDP:        s.config.ForwardsUDP(),
			BindAddr:         s.config.BindAddr,
			Nodelay:          s.config.Nodelay,
			KeepAlive:        time.Duration(s.config.Keepalive) * time.Second,
			Heartbeat:        time.Duration(s.config.Heartbeat) * time.Second,
			Token:            s.config.Token,
			ChannelSize:      s.config.ChannelSize,
			Ports:            s.config.Ports,
			MuxCon:           s.config.MuxCon,
			MuxVersion:       s.config.MuxVersion,
			MaxFrameSize:     s.config.MaxFrameSize,
			MaxReceiveBuffer: s.config.MaxReceiveBuffer,
			MaxStreamBuffer:  s.config.MaxStreamBuffer,
			Mode:             s.config.Transport,
			SimpleAuth:       s.config.SimpleAuth,
			TLSCertFile:      s.config.TLSCertFile,
			ACMEDomain:       s.config.ACMEDomain,
			ACMEEmail:        s.config.ACMEEmail,
			ACMECacheDir:     acmeCacheDir,
			TLSKeyFile:       s.config.TLSKeyFile,
			MSS:              s.config.MSS,
			ProxyProtocol:    s.config.ProxyProtocol,
			MaxConnections:   s.config.MaxConnections,
			BandwidthMbps:    s.config.BandwidthMbps,
		}
		wsMuxServer := transport.NewWSMuxServer(s.ctx, wsMuxConfig, s.logger)
		go wsMuxServer.Start()

	case config.UDP:
		udpConfig := &transport.UdpConfig{
			BindAddr:    s.config.BindAddr,
			Heartbeat:   time.Duration(s.config.Heartbeat) * time.Second,
			Token:       s.config.Token,
			ChannelSize: s.config.ChannelSize,
			Ports:       s.config.Ports,
			SO_RCVBUF:   s.config.SO_RCVBUF,
			SO_SNDBUF:   s.config.SO_SNDBUF,
		}
		udpServer := transport.NewUDPServer(s.ctx, udpConfig, s.logger)
		go udpServer.Start()

	default:
		s.logger.Fatal("invalid transport type: ", s.config.Transport)
	}

	<-s.ctx.Done()
	s.logger.Info("all workers stopped successfully")
	s.logger.SetLevel(logrus.FatalLevel)
}

func (s *Server) Stop() {
	if s.cancel != nil {
		s.cancel()
	}
}
