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

	"github.com/quic-go/quic-go"
	"github.com/sirupsen/logrus"
)

// QuicTransport is the client side of the QUIC transport.
type QuicTransport struct {
	status          tunnelStatus
	config          *QuicConfig
	quicSettings    network.QUICSettings
	parentctx       context.Context
	state           clientState
	logger          *logrus.Logger
	restartMutex    sync.Mutex
	poolConnections int32
	loadConnections int32
	controlFlow     chan struct{}

	connMu   sync.Mutex
	quicConn *quic.Conn
}

type QuicConfig struct {
	RemoteAddr     string
	Endpoints      *network.Endpoints
	Token          string
	KeepAlive      time.Duration
	RetryInterval  time.Duration
	DialTimeOut    time.Duration
	ConnPoolSize   int
	AggressivePool bool
	SO_RCVBUF      int
	SO_SNDBUF      int
}

func (c *QuicConfig) settings() network.QUICSettings {
	return network.QUICSettings{
		KeepAlivePeriod: c.KeepAlive,
		MaxIdleTimeout:  quicIdleTimeout(c.KeepAlive),
		SO_RCVBUF:       c.SO_RCVBUF,
		SO_SNDBUF:       c.SO_SNDBUF,
	}
}

func quicIdleTimeout(keepAlive time.Duration) time.Duration {
	if keepAlive <= 0 {
		return 30 * time.Second
	}
	return 3 * keepAlive
}

func NewQuicClient(parentCtx context.Context, config *QuicConfig, logger *logrus.Logger) *QuicTransport {
	ctx, cancel := context.WithCancel(parentCtx)

	client := &QuicTransport{
		config:       config,
		quicSettings: config.settings(),
		parentctx:    parentCtx,
		logger:       logger,
		controlFlow:  make(chan struct{}, 100),
	}
	client.state.Reset(ctx, cancel)
	return client
}

func (c *QuicTransport) setQUICConn(conn *quic.Conn) {
	c.connMu.Lock()
	c.quicConn = conn
	c.connMu.Unlock()
}

func (c *QuicTransport) getQUICConn() *quic.Conn {
	c.connMu.Lock()
	defer c.connMu.Unlock()
	return c.quicConn
}

func (c *QuicTransport) Start() {
	c.status.set("Disconnected (QUIC)")
	go c.channelDialer()
}

func (c *QuicTransport) Restart() {
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
	if qc := c.getQUICConn(); qc != nil {
		_ = qc.CloseWithError(0, "restart")
		c.setQUICConn(nil)
	}

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

func (c *QuicTransport) channelDialer() {
	c.logger.Info("attempting to establish a new quic control channel connection...")

	bo := newBackoff(c.config.RetryInterval)

	for {
		select {
		case <-c.state.Ctx().Done():
			return
		default:
			conn, err := network.QUICDial(c.state.Ctx(), c.config.Endpoints.Current(), c.quicSettings)
			if err != nil {
				c.logger.Errorf("channel dialer: %v", err)
				if next := c.config.Endpoints.Rotate(); c.config.Endpoints.Len() > 1 {
					c.logger.Infof("trying next server endpoint: %s", next)
				}
				bo.Wait(c.state.Ctx())
				continue
			}

			stream, err := conn.OpenStreamSync(c.state.Ctx())
			if err != nil {
				c.logger.Errorf("failed to open control stream: %v", err)
				_ = conn.CloseWithError(0, "control open failed")
				bo.Wait(c.state.Ctx())
				continue
			}
			control := network.NewQUICStreamConn(stream, conn)

			if err := utils.SendBinaryTransportString(control, c.config.Token, utils.SG_Chan); err != nil {
				c.logger.Errorf("failed to send security token: %v", err)
				_ = conn.CloseWithError(0, "token send failed")
				bo.Wait(c.state.Ctx())
				continue
			}

			if err := control.SetReadDeadline(time.Now().Add(c.config.DialTimeOut)); err != nil {
				c.logger.Errorf("failed to set read deadline: %v", err)
				_ = conn.CloseWithError(0, "deadline failed")
				bo.Wait(c.state.Ctx())
				continue
			}

			message, _, err := utils.ReceiveBinaryTransportString(control)
			if err != nil {
				if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
					c.logger.Warn("timeout while waiting for control channel response")
				} else {
					c.logger.Errorf("failed to receive control channel response: %v", err)
				}
				_ = conn.CloseWithError(0, "no response")
				if next := c.config.Endpoints.Rotate(); c.config.Endpoints.Len() > 1 {
					c.logger.Infof("trying next server endpoint: %s", next)
				}
				bo.Wait(c.state.Ctx())
				continue
			}

			control.SetReadDeadline(time.Time{})

			if message != c.config.Token {
				c.logger.Errorf("invalid token received (does not match the server's token). Retrying...")
				_ = conn.CloseWithError(0, "bad token")
				bo.Wait(c.state.Ctx())
				continue
			}

			c.setQUICConn(conn)
			c.state.SetConn(control)
			c.logger.Info("control channel established successfully")

			metrics.ReportPeer(conn.RemoteAddr().String())
			c.status.set("Connected (QUIC)")

			go c.poolMaintainer()
			go c.channelHandler()

			return
		}
	}
}

func (c *QuicTransport) poolMaintainer() {
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

func (c *QuicTransport) channelHandler() {
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

func (c *QuicTransport) tunnelDialer() {
	qc := c.getQUICConn()
	if qc == nil {
		return
	}

	stream, err := qc.OpenStreamSync(c.state.Ctx())
	if err != nil {
		c.logger.Errorf("failed to open tunnel stream: %v", err)
		return
	}
	data := network.NewQUICStreamConn(stream, qc)

	if err := utils.SendBinaryTransportString(data, c.config.Token, utils.SG_TCP); err != nil {
		c.logger.Errorf("failed to announce tunnel stream: %v", err)
		stream.Close()
		return
	}

	atomic.AddInt32(&c.poolConnections, 1)

	remoteAddr, err := utils.ReceiveBinaryString(data)
	atomic.AddInt32(&c.poolConnections, -1)
	if err != nil {
		c.logger.Tracef("tunnel stream closed before use: %v", err)
		stream.Close()
		return
	}

	c.localDialer(data, remoteAddr)
}

func (c *QuicTransport) dialUDP(stream net.Conn, remoteAddr string) bool {
	return dialForwardedUDP(stream, remoteAddr, c.logger)
}

func (c *QuicTransport) localDialer(stream net.Conn, remoteAddr string) {
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

	handlers.TCPConnectionHandler(c.state.Ctx(), false, metrics.CountedConn(stream), localConnection, c.logger, nil, int(port), false)
}
