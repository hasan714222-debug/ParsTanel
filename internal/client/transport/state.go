package transport

import (
	"context"
	"net"
	"sync"

	"github.com/gorilla/websocket"
)

// clientState holds generation-scoped state replaced on reconnect/restart.
type clientState struct {
	mu     sync.RWMutex
	ctx    context.Context
	cancel context.CancelFunc
	conn   net.Conn        // control channel for the byte-stream transports
	wsConn *websocket.Conn // control channel for the websocket transports
}

// Reset publishes a whole new generation at once.
func (s *clientState) Reset(ctx context.Context, cancel context.CancelFunc) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ctx = ctx
	s.cancel = cancel
	s.conn = nil
	s.wsConn = nil
}

func (s *clientState) Ctx() context.Context {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.ctx
}

func (s *clientState) Cancel() context.CancelFunc {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.cancel
}

func (s *clientState) Conn() net.Conn {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.conn
}

func (s *clientState) SetConn(c net.Conn) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.conn = c
}

func (s *clientState) WSConn() *websocket.Conn {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.wsConn
}

func (s *clientState) SetWSConn(c *websocket.Conn) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.wsConn = c
}

// CloseConn closes whichever control channel is held, if any.
func (s *clientState) CloseConn() {
	if c := s.Conn(); c != nil {
		c.Close()
	}
	if c := s.WSConn(); c != nil {
		c.Close()
	}
}

// drain empties a buffered signal channel without replacing it.
func drain(ch chan struct{}) {
	for {
		select {
		case <-ch:
		default:
			return
		}
	}
}

// tunnelStatus is the one-line state a transport publishes.
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
