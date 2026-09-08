package manage

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/metrics"
)

func TestDatagramTransportsAreRecognised(t *testing.T) {
	for _, tr := range []string{"kcp", "udp"} {
		if !isDatagram(tr) {
			t.Errorf("%s should be treated as a datagram transport", tr)
		}
	}
	for _, tr := range []string{"tcp", "tcpmux", "ws", "wsmux", "wss", "wssmux"} {
		if isDatagram(tr) {
			t.Errorf("%s is not a datagram transport", tr)
		}
	}
}

func TestDatagramServerIsNotReportedOffline(t *testing.T) {
	for _, tr := range []string{"kcp", "udp"} {
		tun := Tunnel{Name: "t", Role: "server", Transport: tr, Addr: "[::]:8989"}
		if !tunnelHealthy(tun, nil) {
			t.Errorf("a running %s server was reported unhealthy with no TCP sockets", tr)
		}
	}
}

func TestTCPServerWithNoPeerIsStillOffline(t *testing.T) {
	tun := Tunnel{Name: "t", Role: "server", Transport: "tcp", Addr: "0.0.0.0:8989"}
	if tunnelHealthy(tun, nil) {
		t.Error("a TCP server with no connected peer should not be reported healthy")
	}
}

func TestDatagramServerNoLongerDisclaimsWhatItCanCheck(t *testing.T) {
	src, err := os.ReadFile("health.go")
	if err != nil {
		t.Fatalf("cannot read health.go: %v", err)
	}
	if strings.Contains(string(src), "cannot report its peers") {
		t.Error("the health detail still says the peer cannot be reported; it is read from the snapshot now")
	}
}

func stageSnapshot(t *testing.T, name, peer string, taken time.Time) string {
	t.Helper()
	dir := t.TempDir()
	body, err := json.Marshal(metrics.Snapshot{Name: name, Peer: peer, Taken: taken})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(metrics.Path(dir, name), body, 0644); err != nil {
		t.Fatalf("staging the snapshot: %v", err)
	}
	return dir
}

func TestDatagramServerWithNoPeerReportsOffline(t *testing.T) {
	for _, tr := range []string{"kcp", "udp"} {
		t.Run(tr, func(t *testing.T) {
			dir := stageSnapshot(t, "t", "", time.Now())

			connected, known := datagramPeer(dir, "t")
			if !known {
				t.Fatal("a fresh snapshot was treated as unreadable")
			}
			if connected {
				t.Error("a cleared peer was read as a live connection — the panel would stay green")
			}
		})
	}
}

func TestDatagramServerWithAPeerReportsOnline(t *testing.T) {
	dir := stageSnapshot(t, "t", "203.0.113.9:41234", time.Now())

	connected, known := datagramPeer(dir, "t")
	if !known || !connected {
		t.Errorf("a reported peer was not read back: connected=%v known=%v", connected, known)
	}
}

func TestUnknownIsNotTheSameAsDisconnected(t *testing.T) {
	dir := stageSnapshot(t, "other", "", time.Now())

	if _, known := datagramPeer(dir, "t"); known {
		t.Error("a missing snapshot was treated as a definite answer")
	}

	dir = stageSnapshot(t, "t", "203.0.113.9:41234", time.Now().Add(-10*time.Minute))
	if _, known := datagramPeer(dir, "t"); known {
		t.Error("a stale snapshot was treated as current")
	}
}

func TestWatchdogStillNeverRestartsADatagramServer(t *testing.T) {
	stageSnapshot(t, "t", "", time.Now())

	for _, tr := range []string{"kcp", "udp"} {
		tun := Tunnel{Name: "t", Role: "server", Transport: tr, Addr: "[::]:8989"}
		if !tunnelHealthy(tun, nil) {
			t.Errorf("%s server reported unhealthy to the watchdog; it would be restarted in a loop", tr)
		}
	}
}

func TestObservabilityFreeCarriersCountAsDatagram(t *testing.T) {
	for _, tr := range []string{"xdi", "pck", "l3/spoof", "kcp", "udp", "quic"} {
		if !isDatagram(tr) {
			t.Errorf("%s must be judged from the snapshot, not the socket table", tr)
		}
	}
}

func TestTheSnapshotAnswersForTheDiallingSideToo(t *testing.T) {
	t.Run("a client that reported its peer is online", func(t *testing.T) {
		dir := stageSnapshot(t, "t", "198.51.100.7:8443", time.Now())
		connected, known := datagramPeer(dir, "t")
		if !known || !connected {
			t.Errorf("a dialling side's peer was not read back: connected=%v known=%v", connected, known)
		}
	})

	t.Run("a client whose control channel dropped is offline", func(t *testing.T) {
		dir := stageSnapshot(t, "t", "", time.Now())
		connected, known := datagramPeer(dir, "t")
		if !known {
			t.Fatal("a fresh snapshot was treated as unreadable")
		}
		if connected {
			t.Error("a cleared peer was read as a live connection")
		}
	})
}

func TestExtendingTheSnapshotCheckLeftTheWatchdogAlone(t *testing.T) {
	stageSnapshot(t, "t", "", time.Now())

	for _, tr := range []string{"xdi", "pck"} {
		tun := Tunnel{Name: "t", Role: "server", Transport: tr, Addr: "[::]:8989"}
		if !tunnelHealthy(tun, nil) {
			t.Errorf("%s server reported unhealthy to the watchdog; it would be restarted in a loop", tr)
		}
	}
}
