package transport

import (
	"bytes"
	"context"
	"fmt"
	"net"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/metrics"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/handlers"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"

	"github.com/gorilla/websocket"
	"github.com/sirupsen/logrus"
)

type WsTransport struct {
	status          tunnelStatus
	config          *WsConfig
	parentctx       context.Context
	state           clientState
	logger          *logrus.Logger
	restartMutex    sync.Mutex
	poolConnections int32
	loadConnections int32
	controlFlow     chan struct{}
}

type WsConfig struct {
	RemoteAddr     string
	Endpoints      *network.Endpoints
	Token          string
	Nodelay        bool
	KeepAlive      time.Duration
	RetryInterval  time.Duration
	DialTimeOut    time.Duration
	ConnPoolSize   int
	Mode           config.TransportType
	SimpleAuth     bool
	AggressivePool bool
	EdgeIP         string
	MSS            int
	Outbound       *network.Outbound
}

func NewWSClient(parentCtx context.Context, config *WsConfig, logger *logrus.Logger) *WsTransport {
	ctx, cancel := context.WithCancel(parentCtx)

	client := &WsTransport{
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

func (c *WsTransport) Start() {
	c.status.set(fmt.Sprintf("Disconnected (%s)", c.config.Mode))
	go c.channelDialer()
}

func (c *WsTransport) Restart() {
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

func (c *WsTransport) channelDialer() {
	c.logger.Info("attempting to establish a new websocket control channel connection")

	bo := newBackoff(c.config.RetryInterval)

	for {
		select {
		case <-c.state.Ctx().Done():
			return
		default:
			tunnelWSConn, err := network.WebSocketDialer(c.state.Ctx(), c.config.Outbound, c.config.Endpoints.Current(), c.config.EdgeIP, "/channel", c.config.DialTimeOut, c.config.KeepAlive, true, c.config.Token, c.config.Mode, c.config.SimpleAuth, 3, 0, 0, c.config.MSS)
			if err != nil {
				c.logger.Errorf("control channel dialer: %v", err)
				if next := c.config.Endpoints.Rotate(); c.config.Endpoints.Len() > 1 {
					c.logger.Infof("trying next server endpoint: %s", next)
				}
				bo.Wait(c.state.Ctx())
				continue
			}

			metrics.ReportPeer(tunnelWSConn.RemoteAddr().String())
			c.state.SetWSConn(tunnelWSConn)
			c.logger.Info("control channel established successfully")

			c.status.set(fmt.Sprintf("Connected (%s)", c.config.Mode))

			go c.poolMaintainer()
			go c.channelHandler()

			return
		}
	}
}

func (c *WsTransport) poolMaintainer() {
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

func (c *WsTransport) channelHandler() {
	msgChan := make(chan byte, 1000)

	go func() {
		for {
			select {
			case <-c.state.Ctx().Done():
				return

			default:
				if err := c.state.WSConn().SetReadDeadline(time.Now().Add(controlDeadline(c.config.KeepAlive))); err != nil {
					if c.state.Cancel() != nil {
						c.logger.Errorf("failed to set control channel deadline: %v", err)
						go c.Restart()
					}
					return
				}
				messageType, msg, err := c.state.WSConn().ReadMessage()
				if err != nil {
					if c.state.Cancel() != nil {
						c.logger.Error("failed to read from channel connection. ", err)
						go c.Restart()
					}
					return
				}

				signal, ok := utils.WebSocketSignal(messageType, msg)
				if !ok {
					c.logger.Warnf("ignoring a malformed control frame (type %d, %d bytes)", messageType, len(msg))
					continue
				}
				msgChan <- signal
			}
		}
	}()

	for {
		select {
		case <-c.state.Ctx().Done():
			_ = c.state.WSConn().WriteMessage(websocket.BinaryMessage, []byte{utils.SG_Closed})
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
				err := c.state.WSConn().WriteMessage(websocket.BinaryMessage, []byte{utils.SG_HB})
				if err != nil {
					c.logger.Errorf("failed to send heartbeat: %v", msg)
					go c.Restart()
					return
				}
				c.logger.Trace("heartbeat signal sent successfully")

			case utils.SG_Closed:
				c.logger.Warn("control channel has been closed by the server")
				go c.Restart()
				return

			default:
				c.logger.Errorf("unexpected response from channel: %v", msg)
				go c.Restart()
				return
			}
		}
	}
}

func (c *WsTransport) tunnelDialer() {
	c.logger.Debugf("initiating new websocket tunnel connection to address %s", c.config.RemoteAddr)

	tunnelConn, err := network.WebSocketDialer(c.state.Ctx(), c.config.Outbound, c.config.Endpoints.Next(), c.config.EdgeIP, "/tunnel", c.config.DialTimeOut, c.config.KeepAlive, c.config.Nodelay, c.config.Token, c.config.Mode, c.config.SimpleAuth, 3, 1024*1024, 1024*1024, c.config.MSS)
	if err != nil {
		c.logger.Errorf("tunnel server dialer: %v", err)
		return
	}

	atomic.AddInt32(&c.poolConnections, 1)

	for {
		select {
		case <-c.state.Ctx().Done():
			return
		default:
			_, remoteAddrBytes, err := tunnelConn.ReadMessage()
			if err != nil {
				c.logger.Debugf("unable to get port from websocket connection %s: %v", tunnelConn.RemoteAddr().String(), err)
				tunnelConn.Close()
				atomic.AddInt32(&c.poolConnections, -1)
				return
			}

			if bytes.Equal(remoteAddrBytes, []byte{utils.SG_Ping}) {
				c.logger.Trace("ping received from the server")
				continue
			}

			atomic.AddInt32(&c.poolConnections, -1)

			remoteAddr := string(remoteAddrBytes)

			if dialForwardedUDP(&wsStream{conn: tunnelConn}, remoteAddr, c.logger) {
				return
			}

			port, resolvedAddr, err := network.ResolveRemoteAddr(remoteAddr)
			if err != nil {
				c.logger.Infof("failed to resolve remote port: %v", err)
				tunnelConn.Close()
				return
			}

			c.localDialer(tunnelConn, resolvedAddr, port)
			return
		}
	}
}

func (c *WsTransport) localDialer(tunnelCon *websocket.Conn, remoteAddr string, port int) {
	resolvedAddr = backends.pick(remoteAddr)
	var sendBuf, recvBuf int

	if strings.Contains(remoteAddr, "127.0.0.1") {
		sendBuf = 32 * 1024
		recvBuf = 32 * 1024
	} else {
		sendBuf = 0
		recvBuf = 0
	}

	localConnection, err := network.TcpDialer(c.state.Ctx(), remoteAddr, c.config.DialTimeOut, c.config.KeepAlive, true, 1, recvBuf, sendBuf, 0)
	if err != nil {
		localDial.Report(c.logger, remoteAddr, err)
		tunnelCon.Close()
		return
	}
	ReportLocalDialOK()
	c.logger.Debugf("connected to local address %s successfully", remoteAddr)

	handlers.WSConnectionHandler(c.state.Ctx(), tunnelCon, localConnection, c.logger, int(port))
}
