package testport

import (
	"fmt"
	"net"
	"os"
	"sync"
	"testing"
)

const (
	low  = 20000
	high = 32000
)

var (
	mu      sync.Mutex
	current = -1
	used    = map[int]bool{}
)

func startFor(pid int) int {
	return low + ((pid * 7919) % (high - low))
}

// Free returns an unused port in the safe test range [low, high).
func Free(t testing.TB) int {
	if h, ok := t.(interface{ Helper() }); ok {
		h.Helper()
	}
	mu.Lock()
	defer mu.Unlock()

	if current < 0 {
		current = startFor(os.Getpid())
	}

	span := high - low
	for i := 0; i < span; i++ {
		port := low + ((current - low + i) % span)
		if used[port] {
			continue
		}
		if !IsFree(port) {
			continue
		}
		used[port] = true
		current = port + 1
		return port
	}

	t.Fatalf("testport: no free ports available in range [%d, %d)", low, high)
	return 0
}

// IsFree checks whether a port can be bound on both TCP and UDP.
func IsFree(port int) bool {
	addr := fmt.Sprintf("127.0.0.1:%d", port)
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return false
	}
	ln.Close()

	pc, err := net.ListenPacket("udp", addr)
	if err != nil {
		return false
	}
	pc.Close()

	return true
}
