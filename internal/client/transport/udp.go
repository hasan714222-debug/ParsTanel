package transport

import (
	"context"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/metrics"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"
	"github.com/sirupsen/logrus"
)

type UdpTransport struct {
	status          tunnelStatus
	config          *UdpConfig
	parentctx       context.Context
	state           clientState
	logger          *logrus.Logger
	restartMutex    sync.Mutex
	poolConnections int32
	loadConnections int32
	controlFlow     chan struct{}
}

type UdpConfig struct {
	RemoteAddr     string
	Endpoints      *network.Endpoints
	Token          string
	RetryInterval  time.Duration
	DialTimeOut    time.Duration
	ConnPoolSize   int
	AggressivePool bool
	SO_RCVBUF      int
	SO_SNDBUF      int
}

func NewUDPClient(parentCtx context.Context, config *UdpConfig, logger *logrus.Logger) *UdpTransport {
	ctx, cancel := context.WithCancel(parentCtx)

	client := &UdpTransport{
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

func (c *UdpTransport) Start() {
	c.status.set("Disconnected (UDP)")
	go c.channelDialer()
}

func (c *UdpTransport) Restart() {
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
	metrics.ClearPeer()
	drain(c.controlFlow)

	c.logger.SetLevel(level)

	go c.Start()
}

func (c *UdpTransport) channelDialer() {
	c.logger.Info("attempting to establish a new control channel connection...")

	bo := newBackoff(c.config.RetryInterval)

	for {
		select {
		case <-c.state.Ctx().Done():
			return
		default:
			tunnelTCPConn, err := network.TcpDialer(c.state.Ctx(), c.config.Endpoints.Current(), c.config.DialTimeOut, 30, true, 3, 0, 0, 0)
			if err != nil {
				c.logger.Errorf("channel dialer: %v", err)
				if next := c.config.Endpoints.Rotate(); c.config.Endpoints.Len() > 1 {
					c.logger.Infof("trying next server endpoint: %s", next)
				}
				bo.Wait(c.state.Ctx())
				continue
			}

			err = utils.SendBinaryTransportString(tunnelTCPConn, c.config.Token, utils.SG_Chan)
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

			message, _, err := utils.ReceiveBinaryTransportString(tunnelTCPConn)
			if err != nil {
				if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
					c.logger.Warn("timeout while waiting for control channel response")
				} else {
					c.logger.Errorf("failed to receive control channel response: %v", err)
				}
				tunnelTCPConn.Close()
				bo.Wait(c.state.Ctx())
				continue
			}
			tunnelTCPConn.SetReadDeadline(time.Time{})

			if message == c.config.Token {
				metrics.ReportPeer(tunnelTCPConn.RemoteAddr().String())
				c.state.SetConn(tunnelTCPConn)
				c.logger.Info("control channel established successfully")

				c.status.set("Connected (UDP)")

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

func (c *UdpTransport) poolMaintainer() {
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

			if (loadConnections + a) > poolConnectionsAvg*b {
				c.logger.Debugf("increasing pool size: %d -> %d, avg pool conn: %d, avg load conn: %d", newPoolSize, newPoolSize+1, poolConnectionsAvg, loadConnections)
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

func (c *UdpTransport) channelHandler() {
	msgChan := make(chan byte, 1000)

	go func() {
		for {
			select {
			case <-c.state.Ctx().Done():
				return
			default:
				if err := c.state.Conn().SetReadDeadline(time.Now().Add(controlDeadline(0))); err != nil {
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

func (c *UdpTransport) applyBuffers(conn *net.UDPConn) {
	if c.config.SO_RCVBUF > 0 {
		if err := conn.SetReadBuffer(c.config.SO_RCVBUF); err != nil {
			c.logger.Warnf("failed to set UDP read buffer to %d: %v", c.config.SO_RCVBUF, err)
		}
	}
	if c.config.SO_SNDBUF > 0 {
		if err := conn.SetWriteBuffer(c.config.SO_SNDBUF); err != nil {
			c.logger.Warnf("failed to set UDP write buffer to %d: %v", c.config.SO_SNDBUF, err)
		}
	}
}

func (c *UdpTransport) tunnelDialer() {
	c.logger.Debugf("initiating new connection to tunnel server at %s", c.config.RemoteAddr)

	remoteAddr, err := net.ResolveUDPAddr("udp", c.config.Endpoints.Next())
	if err != nil {
		c.logger.Error("failed to resolve tunnel address:", err)
		return
	}

	tunConn, err := net.DialUDP("udp", nil, remoteAddr)
	if err != nil {
		c.logger.Error("failed to connect to server:", err)
		return
	}

	c.applyBuffers(tunConn)
	defer tunConn.Close()

	done := make(chan struct{})

	go func() {
		c.handleTunnelConn(tunConn)
		close(done)
	}()

	select {
	case <-done:
	case <-c.state.Ctx().Done():
	}
}

func (c *UdpTransport) handleTunnelConn(tunConn *net.UDPConn) {
	_, err := tunConn.Write([]byte(c.config.Token))
	if err != nil {
		c.logger.Error("faliled to send token:", err)
		return
	}

	atomic.AddInt32(&c.poolConnections, 1)

	buffer := make([]byte, 47)

	for {
		n, _, err := tunConn.ReadFromUDP(buffer)
		if err != nil {
			c.logger.Error("failed to receive response from server:", err)
			atomic.AddInt32(&c.poolConnections, -1)
			return
		}

		if n == 1 && buffer[0] == utils.SG_Ping {
			c.logger.Tracef("ping signal recieved for %s", tunConn.LocalAddr().String())
			continue
		}

		port, remoteAddr, err := network.ResolveRemoteAddr(string(buffer[:n]))
		atomic.AddInt32(&c.poolConnections, -1)

		if err != nil {
			c.logger.Error("failed to find remote address:", err)
			return
		}

		c.localDialer(remoteAddr, port, tunConn)
		break
	}
}

func (c *UdpTransport) localDialer(remoteAddr string, port int, tunConn *net.UDPConn) {
	remoteAddr = firstBackend(remoteAddr)
	remoteResolvedAddr, err := net.ResolveUDPAddr("udp", remoteAddr)
	if err != nil {
		c.logger.Error("failed to resolve remote address:", err)
		return
	}

	remoteConn, err := net.DialUDP("udp", nil, remoteResolvedAddr)
	if err != nil {
		c.logger.Errorf("failed to dial remote UDP address: %v", err)
		return
	}

	c.applyBuffers(remoteConn)
	defer remoteConn.Close()

	done := make(chan struct{})
	c.logger.Debugf("start to copy from tunnel %s to local %s", tunConn.LocalAddr(), remoteAddr)
	go func() {
		c.udpCopy(remoteConn, tunConn, port)
		done <- struct{}{}
	}()

	c.udpCopy(tunConn, remoteConn, port)
	<-done
}

func (c *UdpTransport) udpCopy(srcConn, dstConn *net.UDPConn, port int) {
	buf := make([]byte, 16*1024)
	readTimeout := 60 * time.Second

	for {
		err := srcConn.SetReadDeadline(time.Now().Add(readTimeout))
		if err != nil {
			c.logger.Errorf("failed to set read deadline: %v", err)
			return
		}

		n, _, err := srcConn.ReadFromUDP(buf)
		if err != nil {
			if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
				c.logger.Debug("read from UDP timed out")
				return
			}
			c.logger.Errorf("failed to read from UDP: %v", err)
			return
		}

		totalWritten := 0
		for totalWritten < n {
			w, err := dstConn.Write(buf[totalWritten:n])
			if err != nil {
				c.logger.Errorf("failed to write to UDP %s: %v", dstConn.RemoteAddr().String(), err)
				return
			}
			totalWritten += w
		}

		c.logger.Debugf("forwarded %d bytes from %s to %s", n, srcConn.LocalAddr().String(), dstConn.RemoteAddr().String())
	}
}
