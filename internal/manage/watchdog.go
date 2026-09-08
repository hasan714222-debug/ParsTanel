package manage

import (
	"context"
	"fmt"
	"net"
	"os/exec"
	"strings"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/alerthist"
	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/metrics"
)

// Watchdog tuning.
const (
	wdInterval  = 25 * time.Second // how often to check
	wdThreshold = 2                // consecutive unhealthy checks before acting
	wdCooldown  = 3 * time.Minute  // minimum time between restarts of one tunnel
)

const (
	flapWindow    = time.Hour
	flapThreshold = 4
)

func RunWatchdog(ctx context.Context) {
	fails := map[string]int{}
	lastRestart := map[string]time.Time{}
	restarts := map[string][]time.Time{}
	lastFlapReport := map[string]time.Time{}
	seenHealthy := map[string]bool{}

	ticker := time.NewTicker(wdInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			pairs := establishedPairs()
			for _, t := range List() {
				if !IsActive(t.Service) {
					fails[t.Name] = 0
					continue
				}
				if tunnelHealthy(t, pairs) {
					fails[t.Name] = 0
					seenHealthy[t.Name] = true
					continue
				}
				if !seenHealthy[t.Name] {
					continue
				}
				fails[t.Name]++
				if fails[t.Name] >= wdThreshold && time.Since(lastRestart[t.Name]) > wdCooldown {
					RestartService(t.Service)
					now := time.Now()
					lastRestart[t.Name] = now
					restarts[t.Name] = recentRestarts(restarts[t.Name], now)
					reportRestart(t.Name, restarts[t.Name], lastFlapReport, now)
					fails[t.Name] = 0
					go reportRecovery(t)
				}
			}
		}
	}
}

const recoveryWait = 45 * time.Second

func reportRecovery(t Tunnel) {
	deadline := time.Now().Add(recoveryWait)
	for time.Now().Before(deadline) {
		time.Sleep(3 * time.Second)
		if !IsActive(t.Service) {
			continue
		}
		if tunnelHealthy(t, establishedPairs()) {
			alerthist.RecordEvent("🟢 Tunnel " + t.Name + " is carrying traffic again after the restart")
			return
		}
	}
	alerthist.RecordEvent("🔴 Tunnel " + t.Name + " did not come back after the restart — " +
		"it is running but still not connected")
}

func engineSaysConnected(name string) (connected, known bool) {
	snap, err := metrics.Read(app.ConfigDir, name)
	if err != nil {
		return false, false
	}
	if time.Since(snap.Taken) > datagramPeerWindow {
		return false, false
	}
	if snap.Connected == nil {
		return false, false
	}
	return *snap.Connected, true
}

func tunnelHealthy(t Tunnel, pairs [][2]string) bool {
	if IsDirectKind(t) {
		healthy, known := directHealthy(t, pairs)
		return healthy || !known
	}
	if connected, known := engineSaysConnected(t.Name); known {
		return connected
	}
	if isDatagram(t.Transport) {
		if t.Role == "server" {
			return true
		}
		pairs = establishedUDPPairs()
	}

	if t.Role == "server" {
		if _, tport, err := net.SplitHostPort(t.Addr); err == nil {
			for _, p := range pairs {
				if portOf(p[0]) == tport {
					return true
				}
			}
			return false
		}
		return true
	}
	if rhost, rport, err := net.SplitHostPort(t.Addr); err == nil {
		rip := net.ParseIP(rhost)
		for _, p := range pairs {
			ph, pp, err := net.SplitHostPort(p[1])
			if err != nil || pp != rport {
				continue
			}
			if rip != nil {
				if pip := net.ParseIP(ph); pip == nil || !pip.Equal(rip) {
					continue
				}
			}
			return true
		}
		return false
	}
	return true
}

func establishedPairs() [][2]string {
	out, err := exec.Command("ss", "-Htn", "state", "established").Output()
	if err != nil {
		return nil
	}
	var pairs [][2]string
	for _, line := range strings.Split(string(out), "\n") {
		f := strings.Fields(line)
		if len(f) < 2 {
			continue
		}
		pairs = append(pairs, [2]string{f[len(f)-2], f[len(f)-1]})
	}
	return pairs
}

func establishedUDPPairs() [][2]string {
	out, err := exec.Command("ss", "-Huan").Output()
	if err != nil {
		return nil
	}

	var pairs [][2]string
	for _, line := range strings.Split(string(out), "\n") {
		f := strings.Fields(line)
		if len(f) < 2 {
			continue
		}
		local, peer := f[len(f)-2], f[len(f)-1]
		if !hasRealPeer(peer) {
			continue
		}
		pairs = append(pairs, [2]string{local, peer})
	}
	return pairs
}

func hasRealPeer(peer string) bool {
	if peer == "" {
		return false
	}
	host, port, err := net.SplitHostPort(peer)
	if err != nil {
		return false
	}
	if port == "*" || port == "0" {
		return false
	}
	switch host {
	case "*", "", "0.0.0.0", "::", "[::]":
		return false
	}
	return true
}

func portOf(hostPort string) string {
	if _, p, err := net.SplitHostPort(hostPort); err == nil {
		return p
	}
	return ""
}

func recentRestarts(prev []time.Time, now time.Time) []time.Time {
	out := make([]time.Time, 0, len(prev)+1)
	for _, t := range prev {
		if now.Sub(t) < flapWindow {
			out = append(out, t)
		}
	}
	return append(out, now)
}

func reportRestart(name string, at []time.Time, lastReport map[string]time.Time, now time.Time) {
	if len(at) < flapThreshold {
		alerthist.RecordEvent("🔁 Watchdog restarted tunnel " + name +
			" — it was running but not connected")
		return
	}
	if last, ok := lastReport[name]; ok && now.Sub(last) < flapWindow {
		return
	}
	lastReport[name] = now
	alerthist.RecordEvent(fmt.Sprintf(
		"⚠️ Tunnel %s is flapping — restarted %d times in the last hour. "+
			"It is not failing once, it is failing repeatedly, which usually means the "+
			"path drops full-sized packets (try a TCP MSS clamp) or the link is too "+
			"lossy for the preset. Individual restart alerts for it are suppressed "+
			"while this lasts.", name, len(at)))
}