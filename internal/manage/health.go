package manage

import (
	"fmt"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/metrics"
)

type Health struct {
	Name        string
	Service     string
	Installed   bool
	Active      bool
	Connected   bool
	State       string
	Detail      string
	ServiceDown *ServiceDownDetail
}

type ServiceDownDetail struct {
	Addr     string
	Why      string
	Failures uint64
	Since    time.Time
}

func TunnelHealth(t Tunnel) Health {
	return tunnelHealthWith(t, establishedPairs())
}

func AllHealth() map[string]Health {
	pairs := establishedPairs()
	tunnels := List()

	out := make(map[string]Health, len(tunnels))
	for _, t := range tunnels {
		out[t.Name] = tunnelHealthWith(t, pairs)
	}
	return out
}

func tunnelHealthWith(t Tunnel, pairs [][2]string) Health {
	h := Health{
		Name:      t.Name,
		Service:   t.Service,
		Installed: fileExists(app.ServiceDir + "/" + t.Service),
		Active:    IsActive(t.Service),
	}
	switch {
	case !h.Installed:
		h.State, h.Detail = "stopped", "no systemd unit — the tunnel is not installed"
	case !h.Active:
		h.State, h.Detail = "stopped", "service is not running"
	default:
		h.Connected = tunnelHealthy(t, pairs)

		if isDatagram(t.Transport) {
			if connected, known := datagramPeer(app.ConfigDir, t.Name); known {
				h.Connected = connected
			}
		}

		if IsDirectKind(t) {
			connected, known := directHealthy(t, pairs)
			h.Connected = connected && known
			h.Detail = directStateDetail(t, connected, known)
			h.State = "offline"
			if h.Connected {
				h.State = "online"
			} else if !known {
				h.State = "unknown"
			}
			return h
		}

		if h.Connected {
			h.State = "online"
			h.Detail = "peer connected"
			if d := serviceDown(app.ConfigDir, t.Name); d != nil {
				h.ServiceDown = d
				h.Detail = serviceDownDetail(d)
			}
		} else {
			h.State = "offline"
			if t.Role == "server" {
				h.Detail = "running, but no client is connected yet"
			} else {
				h.Detail = "running, but not connected to the server"
			}
		}
	}
	return h
}

const datagramPeerWindow = 90 * time.Second

func datagramPeer(dir, name string) (connected, known bool) {
	snap, err := metrics.Read(dir, name)
	if err != nil {
		return false, false
	}
	if time.Since(snap.Taken) > datagramPeerWindow {
		return false, false
	}
	return snap.Peer != "", true
}

func serviceDown(dir, name string) *ServiceDownDetail {
	snap, err := metrics.Read(dir, name)
	if err != nil || snap.LocalService == nil {
		return nil
	}
	if time.Since(snap.Taken) > datagramPeerWindow {
		return nil
	}
	ls := snap.LocalService
	return &ServiceDownDetail{
		Addr: ls.Addr, Why: ls.Why, Failures: ls.Failures, Since: ls.Since,
	}
}

func serviceDownDetail(d *ServiceDownDetail) string {
	what := "is not answering"
	switch d.Why {
	case "refused":
		what = "is not listening"
	case "timeout":
		what = "is not answering — a firewall on that machine, or a wedged service"
	}
	return fmt.Sprintf("the tunnel is up, but %s on the far server %s: %d connection(s) refused since %s",
		d.Addr, what, d.Failures, d.Since.Format("15:04"))
}

func WaitServiceActive(service string, timeout time.Duration) bool {
	deadline := time.Now().Add(timeout)
	for {
		if IsActive(service) {
			return true
		}
		if time.Now().After(deadline) {
			return false
		}
		time.Sleep(500 * time.Millisecond)
	}
}