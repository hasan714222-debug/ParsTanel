package manage

import (
	"crypto/rand"
	"fmt"
	"math/big"
	"net"
	"strconv"
	"strings"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

// EnsureSocksPort makes sure the given server tunnel exposes a port that maps
// to the peer's local SOCKS5 proxy, so this node can reach the internet through
// the peer. It returns the exposed port, adding the mapping (and restarting the
// tunnel) if it isn't already present.
func EnsureSocksPort(name string) (int, error) {
	spec, err := loadServerSpec(name)
	if err != nil {
		return 0, err
	}

	for _, p := range spec.Ports {
		if isBotRelayPort(p, spec.Token) {
			if n, e := strconv.Atoi(strings.TrimSpace(strings.SplitN(p, "=", 2)[0])); e == nil {
				return n, nil
			}
		}
	}

	peerPort := app.SocksPortForToken(spec.Token)
	exposed := randomHighPort()
	spec.Ports = append(spec.Ports, fmt.Sprintf("%d=127.0.0.1:%d", exposed, peerPort))
	if _, err := spec.Save(); err != nil {
		return 0, err
	}
	RestartService(app.ServiceName(name))
	return exposed, nil
}

func randomHighPort() int {
	for i := 0; i < 20; i++ {
		n, err := rand.Int(rand.Reader, big.NewInt(40000))
		if err != nil {
			break
		}
		port := 20000 + int(n.Int64())
		if portFree(port) {
			return port
		}
	}
	return 45678
}

func portFree(port int) bool {
	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
	if err != nil {
		return false
	}
	ln.Close()
	return true
}

func LegacySocksInUse(tunnels []Tunnel) bool {
	suffix := fmt.Sprintf("=127.0.0.1:%d", app.SocksInternalPort)
	for _, t := range tunnels {
		for _, p := range t.Ports {
			if strings.HasSuffix(strings.TrimSpace(p), suffix) {
				return true
			}
		}
	}
	return false
}
