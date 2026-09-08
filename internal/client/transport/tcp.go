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
)

type TcpTransport struct {
	status          tunnelStatus
	config          *TcpConfig
	parentctx       context.Context
	state           clientState
	logger          *logrus.Logger
	restartMutex    sync.Mutex
	poolConnections int32
	loadConnections int32
	controlFlow     chan struct{}
	poolNonce       network.PoolNonce
	legacyServer    legacyProbe
}

type TcpConfig struct {
	RemoteAddr     string
	Endpoints      *network.Endpoints
	Token          string
	KeepAlive      time.Duration
	RetryInterval  time.Duration
	DialTimeOut    time.Duration
	ConnPoolSize   int
	Nodelay        bool
	AggressivePool bool
	MSS            int
	SO_RCVBUF      int
	SO_SNDBUF      int
	Outbound       *network.Outbound
	Stealth        bool
}

func (c *TcpTransport) wrapStealth(conn net.Conn) (net.Conn, error) {
	if !c.config.Stealth {
		return conn, nil
	}
	return network.NoiseClientConn(conn, c.config.Token, c.config.DialTimeOut)
}

func NewTCPClient(parentCtx context.Context, config *TcpConfig, logger *logrus.Logger) *TcpTransport {
	ctx, cancel := context.WithCancel(parentCtx)

	client := &TcpTransport{
		config:          config,
		parentctx:       parentCtx,
		logger:          logger,
		poolConnections: 0,
		loadConnections: 0,
		controlFlow:     make(chan struct{}, 100),
	}

	client.state.Reset(ctx, cancel)
	return client
}

func (c *TcpTransport) Start() {
	c.status.set("Disconnected (TCP)")
	go c.channelDialer()
}

func (c *TcpTransport) Restart() {
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
	c.poolNonce.Clear()
	c.legacyServer.reset()
	atomic.StoreInt32(&c.poolConnections, 0)
	atomic.StoreInt32(&c.loadConnections, 0)
	metrics.ClearPool()
	metrics.ClearPeer()
	drain(c.controlFlow)

	c.logger.SetLevel(level)

	go c.Start()
}

func (c *TcpTransport) channelDialer() {
	c.logger.Info("attempting to establish a new control channel connection...")

	bo := newBackoff(c.config.RetryInterval)

	for {
		select {
		case <-c.state.Ctx().Done():
			return
		default:
			rawConn, err := network.TcpDialerVia(c.state.Ctx(), c.config.Outbound, c.config.Endpoints.Current(), c.config.DialTimeOut, c.config.KeepAlive, true, 3, 0, 0, 0)
			if err != nil {
				c.logger.Errorf("channel dialer: %v", err)
				if next := c.config.Endpoints.Rotate(); c.config.Endpoints.Len() > 1 {
					c.logger.Infof("trying next server endpoint: %s", next)
				}
				bo.Wait(c.state.Ctx())
				continue
			}

			tunnelTCPConn, err := c.wrapStealth(rawConn)
			if err != nil {
				c.logger.Errorf("channel dialer: stealth handshake failed: %v", err)
				rawConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}

			signal := c.legacyServer.signal()
			err = utils.SendBinaryTransportString(tunnelTCPConn, c.config.Token, signal)
			if err != nil {
				c.logger.Errorf("failed to send security token: %v", err)
				tunnelTCPConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}

			if err := tunnelTCPConn.SetReadDeadline(time.Now().Add(controlAckTimeout)); err != nil {
				c.logger.Errorf("failed to set read deadline: %v", err)
				tunnelTCPConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}

			message, ackSignal, err := utils.ReceiveBinaryTransportString(tunnelTCPConn)
			if err != nil {
				if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
					c.logger.Warn("timeout while waiting for control channel response")
				} else {
					c.logger.Errorf("failed to receive control channel response: %v", err)
					c.legacyServer.miss(c.logger, signal)
				}
				tunnelTCPConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}
			tunnelTCPConn.SetReadDeadline(time.Time{})

			if why, refused := refusalReason(message, ackSignal); refused {
				c.logger.Error("the tunnel was refused — " + why)
				c.legacyServer.ack(ackSignal)
				tunnelTCPConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}
			token, nonce, _ := decodeControlAck(message, ackSignal)

			if token == c.config.Token {
				c.legacyServer.ack(ackSignal)
				c.poolNonce.Set(nonce)
				metrics.ReportPeer(tunnelTCPConn.RemoteAddr().String())
				c.state.SetConn(tunnelTCPConn)
				c.logger.Info("control channel established successfully")

				c.status.set("Connected (TCP)")
				go c.poolMaintainer()
				go c.channelHandler()

				return

			} else {
				c.logger.Errorf("invalid token received (does not match the server's token). Retrying...")
				tunnelTCPConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}
		}
	}
}

func (c *TcpTransport) poolMaintainer() {
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

func (c *TcpTransport) channelHandler(g *tcpGen) {
	// this is kept for transport abstraction
}

func (c *TcpTransport) channelHandler() {
	msgChan := make(chan byte, 1000)

	go func() {
		for {
			select {
			case <-c.state.Ctx().Done():
				return
			default:
				if err := c.state.Conn().SetReadDeadline(time.Now().Add(controlDeadline(c.config.KeepAlive))); err != nil {
					if c.state.Cancel() != nil {
						c.logger.Errorf("failed to set control channel deadline: %v", err)
						go c.Restart()
					}
					return
				}
				msg, err := utils.ReceiveBinaryByte(c.state.Conn())
				if err != nil {
					if c.state.Cancel() != nil {
						c.logger.Error("failed to read from control channel. ", err)
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

			case utils.SG_RTT:
				err := utils.SendBinaryByte(c.state.Conn(), utils.SG_RTT)
				if err != nil {
					c.logger.Error("failed to send RTT signal, restarting client: ", err)
					go c.Restart()
					return
				}

			default:
				c.logger.Errorf("unexpected response from channel: %v.", msg)
				go c.Restart()
				return
			}
		}
	}
}

func (c *TcpTransport) tunnelDialer() {
	c.logger.Debugf("initiating new connection to tunnel server at %s", c.config.RemoteAddr)

	rawConn, err := network.TcpDialerVia(c.state.Ctx(), c.config.Outbound, c.config.Endpoints.Next(), c.config.DialTimeOut, c.config.KeepAlive, c.config.Nodelay, 3, c.config.SO_RCVBUF, c.config.SO_SNDBUF, c.config.MSS)
	if err != nil {
		c.logger.Error("tunnel server dialer: ", err)
		return
	}

	tcpConn, err := c.wrapStealth(rawConn)
	if err != nil {
		c.logger.Debugf("tunnel dialer: stealth handshake failed: %v", err)
		rawConn.Close()
		return
	}

	if err := announcePoolConn(tcpConn, c.poolNonce.Get()); err != nil {
		c.logger.Debugf("tunnel dialer: failed to announce the pool connection: %v", err)
		tcpConn.Close()
		return
	}

	atomic.AddInt32(&c.poolConnections, 1)

	remoteAddr, transport, err := utils.ReceiveBinaryTransportString(tcpConn)
	atomic.AddInt32(&c.poolConnections, -1)

	if err != nil {
		c.logger.Debugf("failed to receive port from tunnel connection %s: %v", tcpConn.RemoteAddr().String(), err)
		tcpConn.Close()
		return
	}

	if dialForwardedUDP(tcpConn, remoteAddr, c.logger) {
		return
	}

	port, resolvedAddr, err := network.ResolveRemoteAddr(remoteAddr)
	if err != nil {
		c.logger.Infof("failed to resolve remote port: %v", err)
		tcpConn.Close()
		return
	}

	switch transport {
	case utils.SG_TCP:
		c.localDialer(tcpConn, resolvedAddr, port)
	default:
		c.logger.Error("undefined transport. close the connection.")
		tcpConn.Close()
	}
}

func (c *TcpTransport) localDialer(tcpConn net.Conn, resolvedAddr string, port int) {
	resolvedAddr = backends.pick(resolvedAddr)
	var sendBuf, recvBuf int

	if strings.Contains(resolvedAddr, "127.0.0.1") {
		sendBuf = 32 * 1024
		recvBuf = 32 * 1024
	} else {
		sendBuf = c.config.SO_SNDBUF
		recvBuf = c.config.SO_RCVBUF
	}

	localConnection, err := network.TcpDialer(c.state.Ctx(), resolvedAddr, c.config.DialTimeOut, c.config.KeepAlive, true, 1, recvBuf, sendBuf, c.config.MSS)
	if err != nil {
		localDial.Report(c.logger, resolvedAddr, err)
		tcpConn.Close()
		return
	}

	ReportLocalDialOK()
	c.logger.Debugf("connected to local address %s successfully", resolvedAddr)

	handlers.TCPConnectionHandler(c.state.Ctx(), false, metrics.CountedConn(tcpConn), localConnection, c.logger, port)
}
