package config

import "strings"

// DirectConfig is a direct tunnel: the same forwarded ports the reverse tunnel
// serves, with the tunnel dialled the other way round.
type DirectConfig struct {
	Role             string   `toml:"role"`
	Addr             string   `toml:"addr"`
	Token            string   `toml:"token"`
	Transport        string   `toml:"transport"`
	ServerName       string   `toml:"server_name"`
	TLSCertFile      string   `toml:"tls_cert"`
	TLSKeyFile       string   `toml:"tls_key"`
	ACMEDomain       string   `toml:"acme_domain"`
	ACMEEmail        string   `toml:"acme_email"`
	Ports            []string `toml:"ports"`
	AcceptUDP        bool     `toml:"accept_udp"`
	MaxConnections   int      `toml:"max_connections"`
	BandwidthMbps    int      `toml:"bandwidth_mbps"`
	Preset           string   `toml:"preset"`
	Sessions         int      `toml:"sessions"`
	DialTimeout      int      `toml:"dial_timeout"`
	RetryInterval    int      `toml:"retry_interval"`
	Keepalive        int      `toml:"keepalive_period"`
	Nodelay          bool     `toml:"nodelay"`
	MSS              int      `toml:"mss"`
	MuxVersion       int      `toml:"mux_version"`
	MaxFrameSize     int      `toml:"mux_framesize"`
	MaxReceiveBuffer int      `toml:"mux_recievebuffer"`
	MaxStreamBuffer  int      `toml:"mux_streambuffer"`
}

func (d DirectConfig) Enabled() bool {
	return strings.TrimSpace(d.Role) != ""
}

func (d DirectConfig) ResolvedRole() string {
	switch strings.ToLower(strings.TrimSpace(d.Role)) {
	case "iran", "edge":
		return "edge"
	case "kharej", "origin":
		return "origin"
	default:
		return strings.ToLower(strings.TrimSpace(d.Role))
	}
}
