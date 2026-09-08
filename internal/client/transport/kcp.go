package transport

import (
	"context"
	"net"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/metrics"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/handlers"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"

	"github.com/sirupsen/logrus"
	"github.com/xtaci/kcp-go/v5"
	"github.com/xtaci/smux"
)

// KcpTransport is the client side of the KCP transport.
type KcpTransport struct {
	status          tunnelStatus
	config          *KcpConfig
	smuxConfig      *smux.Config
	kcpSettings     network.KCPSettings
	parentctx       context.Context
	state           clientState
	logger          *logrus.Logger
	restartMutex    sync.Mutex
	poolConnections int32
	loadConnections int32
	controlFlow     chan struct{}
}

type KcpConfig struct {
	RemoteAddr       string
	Endpoints        *network.Endpoints
	Token            string
	KeepAlive        time.Duration
	RetryInterval    time.Duration
	DialTimeOut      time.Duration
	MuxVersion       int
	MaxFrameSize     int
	MaxReceiveBuffer int
	MaxStreamBuffer  int
	ConnPoolSize     int
	AggressivePool   bool
	SO_RCVBUF        int
	SO_SNDBUF        int

	MTU          int
	Interval     int
	Resend       int
	NoDelay      int
	NoCongestion int
	SndWnd       int
	RcvWnd       int
	AckNoDelay   bool
	DataShards   int
	ParityShards int
	UseICMP      bool
	UsePck       bool
	PckInterface  string
	PckGatewayMAC string
	PckFlags      []string
}

func (c *KcpTransport) transportLabel() string {
	if c.config.UseICMP {
		return "XDI"
	}
	if c.config.UsePck {
		return "PCK"
	}
	return "KCP"
}

func (c *KcpConfig) settings() network.KCPSettings {
	s := network.KCPSettings{
		MTU:          c.MTU,
		Interval:     c.Interval,
		Resend:       c.Resend,
		NoDelay:      c.NoDelay,
		NoCongestion: c.NoCongestion,
		SndWnd:       c.SndWnd,
		RcvWnd:       c.RcvWnd,
		AckNoDelay:   c.AckNoDelay,
		DataShards:   c.DataShards,
		ParityShards: c.ParityShards,
		SO_RCVBUF:    c.SO_RCVBUF,
		SO_SNDBUF:    c.SO_SNDBUF,
		UseICMP:      c.UseICMP,
	}
	if c.UsePck {
		flags, err := network.ParseTCPFlagList(c.PckFlags)
		if err != nil {
			flags, _ = network.ParseTCPFlagList(nil)
		}
		s.Pck = &network.PcapCarrier{
			Interface:  c.PckInterface,
			GatewayMAC: c.PckGatewayMAC,
			Flags:      flags,
		}
	}
	return s
}

func NewKcpClient(parentCtx context.Context, config *KcpConfig, logger *logrus.Logger) *KcpTransport {
	ctx, cancel := context.WithCancel(parentCtx)

	client := &KcpTransport{
		smuxConfig: &smux.Config{
			Version:           network.ResolveStaticMuxVersion(config.MuxVersion),
			KeepAliveInterval: 20 * time.Second,
			KeepAliveTimeout:  40 * time.Second,
			MaxFrameSize:      config.MaxFrameSize,
			MaxReceiveBuffer:  config.MaxReceiveBuffer,
			MaxStreamBuffer:   config.MaxStreamBuffer,
		},
		config:          config,
		kcpSettings:     config.settings(),
		parentctx:       parentCtx,
		logger:          logger,
		poolConnections: 0,
		loadConnections: 0,
		controlFlow:     make(chan struct{}, 100),
	}
	client.kcpSettings.Logf = logger.Infof
	client.state.Reset(ctx, cancel)
	return client
}

func (c *KcpTransport) Start() {
	c.status.set("Disconnected (" + c.transportLabel() + ")")
	go c.channelDialer()
}

func (c *KcpTransport) Restart() {
	if !c.restartMutex.TryLock() {
		c.logger.Warn("client is already restarting")
		return
	}
	defer c.restartMutex.Unlock()

	c.logger.Info("restarting client...")

	level := c.logger.GetLevel()
	c.logger.SetLevel(logrus.FatalLevel)

	if c.state.Cancel() != nil {
		c.state.Cancel()()
	}

	c.state.CloseConn()

	time.Sleep(2 * time.Second)

	if c.parentctx.Err() != nil {
		c.logger.SetLevel(level)
		c.logger.Debug("restart abandoned: the tunnel is shutting down")
		return
	}

	ctx, cancel := context.WithCancel(c.parentctx)

	c.state.Reset(ctx, cancel)
	c.status.set("")
	atomic.StoreInt32(&c.poolConnections, 0)
	atomic.StoreInt32(&c.loadConnections, 0)
	metrics.ClearPool()
	metrics.ClearPeer()
	drain(c.controlFlow)

	c.logger.SetLevel(level)

	go c.Start()
}

func (c *KcpTransport) dial(addr string) (*kcp.UDPSession, error) {
	session, err := network.KCPDial(addr, c.config.Token, c.kcpSettings)
	if err != nil {
		return nil, err
	}
	return session, nil
}

func (c *KcpTransport) channelDialer() {
	c.logger.Info("attempting to establish a new kcp control channel connection...")

	bo := newBackoff(c.config.RetryInterval)

	for {
		select {
		case <-c.state.Ctx().Done():
			return
		default:
			tunnelConn, err := c.dial(c.config.Endpoints.Current())
			if err != nil {
				c.logger.Errorf("channel dialer: %v", err)
				if next := c.config.Endpoints.Rotate(); c.config.Endpoints.Len() > 1 {
					c.logger.Infof("trying next server endpoint: %s", next)
				}
				bo.Wait(c.state.Ctx())
				continue
			}

			tunnelConn.SetACKNoDelay(true)

			if err := utils.SendBinaryTransportString(tunnelConn, c.config.Token, utils.SG_Chan); err != nil {
				c.logger.Errorf("failed to send security token: %v", err)
				tunnelConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}

			if err := tunnelConn.SetReadDeadline(time.Now().Add(c.config.DialTimeOut)); err != nil {
				c.logger.Errorf("failed to set read deadline: %v", err)
				tunnelConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}

			message, _, err := utils.ReceiveBinaryTransportString(tunnelConn)
			if err != nil {
				if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
					c.logger.Warn("timeout while waiting for control channel response")
				} else {
					c.logger.Errorf("failed to receive control channel response: %v", err)
				}
				tunnelConn.Close()
				if next := c.config.Endpoints.Rotate(); c.config.Endpoints.Len() > 1 {
					c.logger.Infof("trying next server endpoint: %s", next)
				}
				bo.Wait(c.state.Ctx())
				continue
			}

			tunnelConn.SetReadDeadline(time.Time{})

			if message != c.config.Token {
				c.logger.Errorf("invalid token received (does not match the server's token). Retrying...")
				tunnelConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}

			c.state.SetConn(tunnelConn)
			c.logger.Info("control channel established successfully")

			metrics.ReportPeer(tunnelConn.RemoteAddr().String())
			c.status.set("Connected (" + c.transportLabel() + ")")

			go c.poolMaintainer()
			go c.channelHandler()

			return
		}
	}
}

func (c *KcpTransport) poolMaintainer() {
	for i := 0; i < c.config.ConnPoolSize; i++ {
		go c.tunnelDialer()
	}

	a := 4
	b := 5
	x := 3
	y := 4.0

	if c.config.AggressivePool {
		c.logger.Info("aggressive pool management enabled")
		a = 1
		b = 2
		x = 0
		y = 0.75
	}

	tickerPool := time.NewTicker(time.Second * 1)
	defer tickerPool.Stop()

	tickerLoad := time.NewTicker(time.Second * 10)
	defer tickerLoad.Stop()

	newPoolSize := c.config.ConnPoolSize
	var load poolLoad
	var poolConnectionsSum int32 = 0

	for {
		select {
		case <-c.state.Ctx().Done():
			return

		case <-tickerPool.C:
			atomic.AddInt32(&poolConnectionsSum, atomic.LoadInt32(&c.poolConnections))

		case <-tickerLoad.C:
			loadConnections := (int(atomic.LoadInt32(&c.loadConnections)) + 9) / 10
			atomic.StoreInt32(&c.loadConnections, 0)

			poolConnectionsAvg := (int(atomic.LoadInt32(&poolConnectionsSum)) + 9) / 10
			atomic.StoreInt32(&poolConnectionsSum, 0)

			mbps := load.mbps()

			metrics.ReportPool(poolConnectionsAvg, newPoolSize, c.config.ConnPoolSize, mbps)

			if ((loadConnections+a) > poolConnectionsAvg*b && poolCanGrow(newPoolSize, c.config.ConnPoolSize)) ||
				load.wantsMore(mbps, poolConnectionsAvg, newPoolSize, c.config.ConnPoolSize) {
				c.logger.Debugf("increasing pool size: %d -> %d, avg pool conn: %d, avg load conn: %d, throughput: %d Mbit/s", newPoolSize, newPoolSize+1, poolConnectionsAvg, loadConnections, mbps)
				newPoolSize++
				go c.tunnelDialer()
			} else if float64(loadConnections+x) < float64(poolConnectionsAvg)*y && newPoolSize > c.config.ConnPoolSize {
				c.logger.Debugf("decreasing pool size: %d -> %d, avg pool conn: %d, avg load conn: %d", newPoolSize, newPoolSize-1, poolConnectionsAvg, loadConnections)
				newPoolSize--
				c.controlFlow <- struct{}{}
			}
		}
	}
}

func (c *KcpTransport) channelHandler() {
	msgChan := make(chan byte, 1000)

	go func() {
		for {
			select {
			case <-c.state.Ctx().Done():
				return
			default:
				if err := c.state.Conn().SetReadDeadline(time.Now().Add(controlDeadline(c.config.KeepAlive))); err != nil {
					c.logger.Errorf("failed to set control channel deadline: %v", err)
					go c.Restart()
					return
				}
				msg, err := utils.ReceiveBinaryByte(c.state.Conn())
				if err != nil {
					if c.state.Cancel() != nil {
						if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
							c.logger.Warn("no heartbeat from the server within the keepalive period, reconnecting")
						} else {
							c.logger.Error("failed to read from control channel. ", err)
						}
						go c.Restart()
					}
					return
				}
				msgChan <- msg
			}
		}
	}()

	for {
		select {
		case <-c.state.Ctx().Done():
			_ = utils.SendBinaryByte(c.state.Conn(), utils.SG_Closed)
			return

		case msg := <-msgChan:
			switch msg {
			case utils.SG_Chan:
				atomic.AddInt32(&c.loadConnections, 1)

				select {
				case <-c.controlFlow:
				default:
					c.logger.Debug("channel signal received, initiating tunnel dialer")
					go c.tunnelDialer()
				}

			case utils.SG_HB:
				c.logger.Debug("heartbeat signal received successfully")

			case utils.SG_Closed:
				c.logger.Warn("control channel has been closed by the server")
				go c.Restart()
				return

			default:
				c.logger.Errorf("unexpected response from channel: %v.", msg)
				go c.Restart()
				return
			}
		}
	}
}

func (c *KcpTransport) tunnelDialer() {
	addr := c.config.Endpoints.Next()
	c.logger.Debugf("initiating new tunnel connection to address %s", addr)

	tunnelConn, err := c.dial(addr)
	if err != nil {
		c.logger.Errorf("tunnel server dialer: %v", err)
		return
	}

	if err := utils.SendBinaryTransportString(tunnelConn, c.config.Token, utils.SG_TCP); err != nil {
		c.logger.Errorf("failed to announce tunnel connection: %v", err)
		tunnelConn.Close()
		return
	}

	atomic.AddInt32(&c.poolConnections, 1)
	c.handleSession(tunnelConn)
}

func (c *KcpTransport) handleSession(tunnelConn net.Conn) {
	defer func() {
		atomic.AddInt32(&c.poolConnections, -1)
	}()

	session, err := smux.Server(tunnelConn, c.smuxConfig)
	if err != nil {
		c.logger.Errorf("failed to create mux session: %v", err)
		tunnelConn.Close()
		return
	}

	for {
		select {
		case <-c.state.Ctx().Done():
			return
		default:
			stream, err := session.AcceptStream()
			if err != nil {
				c.logger.Trace("session is closed: ", err)
				session.Close()
				return
			}

			remoteAddr, err := utils.ReceiveBinaryString(stream)
			if err != nil {
				c.logger.Errorf("unable to get port from stream connection %s: %v", tunnelConn.RemoteAddr().String(), err)
				stream.Close()
				continue
			}

			go c.localDialer(stream, remoteAddr)
		}
	}
}

func (c *KcpTransport) dialUDP(stream net.Conn, remoteAddr string) bool {
	return dialForwardedUDP(stream, remoteAddr, c.logger)
}

func (c *KcpTransport) localDialer(stream *smux.Stream, remoteAddr string) {
	if c.dialUDP(stream, remoteAddr) {
		return
	}
	port, resolvedAddr, err := network.ResolveRemoteAddr(remoteAddr)
	if err != nil {
		c.logger.Infof("failed to resolve remote port: %v", err)
		stream.Close()
		return
	}
	resolvedAddr = backends.pick(resolvedAddr)

	var sendBuf, recvBuf int

	if strings.Contains(resolvedAddr, "127.0.0.1") {
		sendBuf = 32 * 1024
		recvBuf = 32 * 1024
	} else {
		sendBuf = c.config.SO_SNDBUF
		recvBuf = c.config.SO_RCVBUF
	}

	localConnection, err := network.TcpDialer(c.state.Ctx(), resolvedAddr, c.config.DialTimeOut, c.config.KeepAlive, true, 1, recvBuf, sendBuf, 0)
	if err != nil {
		localDial.Report(c.logger, resolvedAddr, err)
		stream.Close()
		return
	}

	ReportLocalDialOK()
	c.logger.Debugf("connected to local address %s successfully", remoteAddr)

	handlers.TCPConnectionHandler(c.state.Ctx(), false, metrics.CountedConn(stream), localConnection, c.logger, int(port))
}