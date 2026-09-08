package transport

import (
	"io"
	"net"
	"sync"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"
	"github.com/gorilla/websocket"
	"github.com/sirupsen/logrus"
)

const udpBackendIdle = 60 * time.Second

func dialForwardedUDP(stream net.Conn, remoteAddr string, logger *logrus.Logger) bool {
	target, isUDP := network.SplitUDPTarget(remoteAddr)
	if !isUDP {
		return false
	}
	port, resolved, err := network.ResolveRemoteAddr(target)
	if err != nil {
		logger.Infof("failed to resolve the UDP target %q: %v", target, err)
		stream.Close()
		return true
	}
	UDPForward(stream, resolved, logger, port)
	return true
}

func UDPForward(stream net.Conn, target string, logger *logrus.Logger, port int) {
	target = firstUDPBackend(target)

	addr, err := net.ResolveUDPAddr("udp", target)
	if err != nil {
		logger.Errorf("failed to resolve UDP target %q: %v", target, err)
		stream.Close()
		return
	}
	backend, err := net.DialUDP("udp", nil, addr)
	if err != nil {
		logger.Errorf("failed to dial UDP backend %q: %v", target, err)
		stream.Close()
		return
	}

	logger.Debugf("forwarding UDP to %s", target)

	var once sync.Once
	shutdown := func() {
		once.Do(func() {
			stream.Close()
			backend.Close()
		})
	}
	defer shutdown()

	done := make(chan struct{})
	go func() {
		defer close(done)
		defer shutdown()
		backendToTunnel(stream, backend, logger, port)
	}()

	tunnelToBackend(stream, backend, logger, port)
	shutdown()
	<-done
}

func tunnelToBackend(stream net.Conn, backend *net.UDPConn, logger *logrus.Logger, port int) {
	buf := make([]byte, network.MaxDatagram)
	for {
		n, err := network.ReadDatagram(stream, buf)
		if err != nil {
			logger.Tracef("UDP flow to %s ended: %v", backend.RemoteAddr(), err)
			return
		}
		if _, err := backend.Write(buf[:n]); err != nil {
			logger.Debugf("failed to write to UDP backend %s: %v", backend.RemoteAddr(), err)
			return
		}
	}
}

func backendToTunnel(stream net.Conn, backend *net.UDPConn, logger *logrus.Logger, port int) {
	buf := make([]byte, network.MaxDatagram)
	for {
		_ = backend.SetReadDeadline(time.Now().Add(udpBackendIdle))
		n, err := backend.Read(buf)
		if err != nil {
			logger.Tracef("UDP backend %s ended: %v", backend.RemoteAddr(), err)
			return
		}
		if err := network.WriteDatagram(stream, buf[:n]); err != nil {
			logger.Debugf("failed to write a datagram to the tunnel: %v", err)
			return
		}
	}
}

type wsStream struct {
	conn *websocket.Conn
	r    io.Reader
}

func (w *wsStream) Read(p []byte) (int, error) {
	for {
		if w.r == nil {
			typ, r, err := w.conn.NextReader()
			if err != nil {
				return 0, err
			}
			if typ != websocket.BinaryMessage && typ != websocket.TextMessage {
				continue
			}
			w.r = r
		}
		n, err := w.r.Read(p)
		if err == io.EOF {
			w.r = nil
			if n > 0 {
				return n, nil
			}
			continue
		}
		return n, err
	}
}

func (w *wsStream) Write(p []byte) (int, error) {
	if err := w.conn.WriteMessage(websocket.BinaryMessage, p); err != nil {
		return 0, err
	}
	return len(p), nil
}

func (w *wsStream) Close() error                       { return w.conn.Close() }
func (w *wsStream) LocalAddr() net.Addr                { return w.conn.LocalAddr() }
func (w *wsStream) RemoteAddr() net.Addr               { return w.conn.RemoteAddr() }
func (w *wsStream) SetDeadline(t time.Time) error      { return w.conn.SetReadDeadline(t) }
func (w *wsStream) SetReadDeadline(t time.Time) error  { return w.conn.SetReadDeadline(t) }
func (w *wsStream) SetWriteDeadline(t time.Time) error { return w.conn.SetWriteDeadline(t) }

func firstUDPBackend(addr string) string {
	for i := 0; i < len(addr); i++ {
		if addr[i] == '|' {
			return addr[:i]
		}
	}
	return addr
}