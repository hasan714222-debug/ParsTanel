package transport

import (
	"context"
	"errors"
	"net"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

func enableKeepAlive(conn net.Conn, period time.Duration) {
	tcp, ok := conn.(*net.TCPConn)
	if !ok {
		return
	}
	_ = tcp.SetKeepAlive(true)
	_ = tcp.SetKeepAlivePeriod(period)
}

func sameHost(a, b net.Addr) bool {
	if a == nil || b == nil {
		return false
	}
	ha, _, err := net.SplitHostPort(a.String())
	if err != nil {
		return false
	}
	hb, _, err := net.SplitHostPort(b.String())
	if err != nil {
		return false
	}
	ipa, ipb := net.ParseIP(ha), net.ParseIP(hb)
	if ipa == nil || ipb == nil {
		return ha == hb
	}
	return ipa.Equal(ipb)
}

const controlWriteTimeout = 10 * time.Second

type netControl struct {
	mu   sync.RWMutex
	conn net.Conn
}

func (c *netControl) Get() net.Conn {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.conn
}

func (c *netControl) Set(conn net.Conn) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.conn = conn
}

func (c *netControl) Clear() {
	c.Set(nil)
}

func (c *netControl) IsSet() bool {
	return c.Get() != nil
}

func (c *netControl) Close() {
	if conn := c.Get(); conn != nil {
		conn.Close()
	}
}

func (c *netControl) RemoteAddr() net.Addr {
	if conn := c.Get(); conn != nil {
		return conn.RemoteAddr()
	}
	return nil
}

type wsControl struct {
	mu   sync.RWMutex
	conn *websocket.Conn
}

func (c *wsControl) Get() *websocket.Conn {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.conn
}

func (c *wsControl) Set(conn *websocket.Conn) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.conn = conn
}

func (c *wsControl) Clear() { c.Set(nil) }

func (c *wsControl) IsSet() bool { return c.Get() != nil }

func (c *wsControl) Close() {
	if conn := c.Get(); conn != nil {
		conn.Close()
	}
}

type runState struct {
	mu     sync.RWMutex
	ctx    context.Context
	cancel context.CancelFunc
}

func (r *runState) set(ctx context.Context, cancel context.CancelFunc) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.ctx, r.cancel = ctx, cancel
}

func (r *runState) context() context.Context {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.ctx
}

func (r *runState) stop() {
	r.mu.RLock()
	cancel := r.cancel
	r.mu.RUnlock()
	if cancel != nil {
		cancel()
	}
}

type tunnelStatus struct {
	mu sync.RWMutex
	s  string
}

func (t *tunnelStatus) set(v string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.s = v
}

func (t *tunnelStatus) get() string {
	t.mu.RLock()
	defer t.mu.RUnlock()
	return t.s
}

func writeControl(conn *websocket.Conn, payload []byte) error {
	if conn == nil {
		return errNoControlChannel
	}
	if err := conn.SetWriteDeadline(time.Now().Add(controlWriteTimeout)); err == nil {
		defer func() { _ = conn.SetWriteDeadline(time.Time{}) }()
	}
	return conn.WriteMessage(websocket.BinaryMessage, payload)
}

var errNoControlChannel = errors.New("no control channel")