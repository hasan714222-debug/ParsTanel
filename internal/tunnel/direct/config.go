package direct

import (
	"fmt"
	"net"
	"strings"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/tunnel/portmap"
)

const (
	RoleEdge   = "edge"
	RoleOrigin = "origin"
)

const (
	TransportTCP     = "tcp"
	TransportStealth = "stealth"
	TransportWS      = "ws"
	TransportWSS     = "wss"
)

const (
	defaultDialTimeout  = 10 * time.Second
	defaultRetryDelay   = 3 * time.Second
	defaultBackendDial  = 10 * time.Second
	defaultMaxFrameSize = 32768
	defaultMaxReceive   = 4194304
	defaultMaxStream    = 65536

	defaultACMECacheDir = "/etc/parstanel/acme"
)

type Config struct {
	Role             string
	Addr             string
	Token            string
	Transport        string
	ServerName       string
	TLSCertFile      string
	TLSKeyFile       string
	ACMEDomain       string
	ACMEEmail        string
	ACMECacheDir     string
	Ports            []string
	AcceptUDP        bool
	MaxConnections   int
	BandwidthMbps    int
	Sessions         int
	DialTimeout      time.Duration
	RetryDelay       time.Duration
	MaxFrameSize     int
	MaxReceiveBuffer int
	MaxStreamBuffer  int
	MuxVersion       int
	Nodelay          bool
	Keepalive        time.Duration
	MSS              int
}

func (c *Config) Validate() error {
	c.Role = strings.ToLower(strings.TrimSpace(c.Role))
	switch c.Role {
	case RoleEdge, RoleOrigin:
	case "":
		return fmt.Errorf("direct: role is required (%q on the Iran server, %q on the kharej server)",
			RoleEdge, RoleOrigin)
	default:
		return fmt.Errorf("direct: unknown role %q (want %q or %q)", c.Role, RoleEdge, RoleOrigin)
	}

	if strings.TrimSpace(c.Addr) == "" {
		if c.Role == RoleEdge {
			return fmt.Errorf("direct: addr is required and must be the kharej server's host:port")
		}
		return fmt.Errorf("direct: addr is required and must be the address to bind")
	}
	if _, _, err := net.SplitHostPort(c.Addr); err != nil {
		return fmt.Errorf("direct: addr %q must be host:port: %w", c.Addr, err)
	}

	if strings.TrimSpace(c.Token) == "" {
		return fmt.Errorf("direct: token is required and must match the other end")
	}

	c.Transport = strings.ToLower(strings.TrimSpace(c.Transport))
	switch c.Transport {
	case "":
		c.Transport = TransportTCP
	case TransportTCP, TransportStealth, TransportWS, TransportWSS:
	default:
		return fmt.Errorf("direct: transport %q is not available (have %q, %q, %q, %q)",
			c.Transport, TransportTCP, TransportStealth, TransportWS, TransportWSS)
	}
	if (c.TLSCertFile == "") != (c.TLSKeyFile == "") {
		return fmt.Errorf("direct: tls_cert and tls_key must be given together")
	}
	if c.ACMECacheDir == "" {
		c.ACMECacheDir = defaultACMECacheDir
	}

	if c.Role == RoleEdge {
		if len(c.Ports) == 0 {
			return fmt.Errorf("direct: the %s needs at least one forwarded port mapping", RoleEdge)
		}
		if _, err := portmap.Expand(c.Ports, DefaultBackendHost); err != nil {
			return fmt.Errorf("direct: %w", err)
		}
	}

	if c.Sessions <= 0 {
		c.Sessions = 1
	}
	if c.Sessions > 64 {
		return fmt.Errorf("direct: sessions = %d is more than the 64 a tunnel can use", c.Sessions)
	}
	if c.DialTimeout <= 0 {
		c.DialTimeout = defaultDialTimeout
	}
	if c.RetryDelay <= 0 {
		c.RetryDelay = defaultRetryDelay
	}
	if c.MaxFrameSize <= 0 {
		c.MaxFrameSize = defaultMaxFrameSize
	}
	if c.MaxReceiveBuffer <= 0 {
		c.MaxReceiveBuffer = defaultMaxReceive
	}
	if c.MaxStreamBuffer <= 0 {
		c.MaxStreamBuffer = defaultMaxStream
	}
	return nil
}