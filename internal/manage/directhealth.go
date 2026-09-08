package manage

import (
	"net"
	"strings"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

func directHealthy(t Tunnel, pairs [][2]string) (healthy, known bool) {
	if strings.HasPrefix(t.Transport, "l3/") {
		return datagramPeer(app.ConfigDir, t.Name)
	}
	if !strings.HasPrefix(t.Transport, "direct/") {
		return false, false
	}

	if t.Role == "kharej" {
		_, port, err := net.SplitHostPort(t.Addr)
		if err != nil {
			return true, false
		}
		for _, p := range pairs {
			if portOf(p[0]) == port {
				return true, true
			}
		}
		return false, true
	}

	host, port, err := net.SplitHostPort(t.Addr)
	if err != nil {
		return true, false
	}
	want := net.ParseIP(host)
	for _, p := range pairs {
		peerHost, peerPort, err := net.SplitHostPort(p[1])
		if err != nil || peerPort != port {
			continue
		}
		if want != nil {
			if got := net.ParseIP(peerHost); got == nil || !got.Equal(want) {
				continue
			}
		}
		return true, true
	}
	return false, true
}

func directStateDetail(t Tunnel, connected, known bool) string {
	if !known {
		return "running, but it has not reported its state yet"
	}
	if connected {
		return "peer connected"
	}
	if t.Role == "kharej" {
		return "running, but the Iran server has not connected yet"
	}
	return "running, but not connected to the kharej server"
}
