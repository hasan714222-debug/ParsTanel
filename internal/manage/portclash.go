package manage

import (
	"fmt"
	"net"
	"strings"
)

// portClash checks whether a tunnel being created or edited conflicts with an
// existing tunnel's bind port (server) or remote address (client).
func portClash(role, addr, self string) string {
	role = strings.ToLower(strings.TrimSpace(role))
	_, port, err := net.SplitHostPort(addr)
	if err != nil {
		return ""
	}

	for _, t := range List() {
		if t.Name == self {
			continue
		}
		if role == "server" && (t.Role == "server" || t.Role == "iran") {
			_, tPort, err := net.SplitHostPort(t.Addr)
			if err == nil && tPort == port {
				return fmt.Sprintf("another server tunnel (%q) is already using port %s on this machine", t.Name, port)
			}
		} else if role == "client" && (t.Role == "client" || t.Role == "kharej") {
			if strings.EqualFold(t.Addr, addr) {
				return fmt.Sprintf("another client tunnel (%q) is already dialling %s", t.Name, addr)
			}
		}
	}
	return ""
}