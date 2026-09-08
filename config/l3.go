package config

import "strings"

// L3Config is a direct layer-3 tunnel: an interface on each host carrying
// whole IP packets between them, rather than a set of forwarded ports.
//
// It lives in its own [l3] table, entirely apart from [server] and [client].
// That separation is deliberate and load-bearing: a configuration that does
// not mention [l3] cannot reach the layer-3 engine, and one that does never
// reaches the reverse tunnel.
type L3Config struct {
	// Mode is "dial" or "listen". Empty means there is no layer-3 tunnel in
	// this configuration.
	Mode string `toml:"mode"`

	// Addr is the peer's host:port when dialling, or the address to bind when
	// listening.
	Addr string `toml:"addr"`

	// Token is the shared secret. It is the only credential.
	Token string `toml:"token"`

	// Carrier is the datagram transport underneath: "udp", "pck", "quic", "sni", "xdi" or "spoof".
	Carrier string `toml:"carrier"`

	// Encap is "gre".
	Encap string `toml:"encap"`

	// GREKey is the RFC 2890 key. Zero omits the field. Ignored unless encap is "gre".
	GREKey uint32 `toml:"gre_key"`

	// SNIDomain is the server name the "sni" carrier puts in that hello.
	SNIDomain string `toml:"sni_domain"`

	// Iface is the interface to create. Empty makes "bp0".
	Iface string `toml:"iface"`

	// LocalIP is this end's address on the tunnel, normally with a prefix: "10.10.0.1/30".
	LocalIP string `toml:"local_ip"`

	// PeerIP is the other end's address on the tunnel.
	PeerIP string `toml:"peer_ip"`

	// MTU is the interface MTU. Zero takes a conservative default.
	MTU int `toml:"mtu"`

	// SockBuf sizes the carrier's socket buffers in bytes.
	SockBuf int `toml:"sockbuf"`

	// FECData and FECParity add forward error correction to the carrier.
	FECData   int `toml:"fec_data"`
	FECParity int `toml:"fec_parity"`

	// Paths spreads the udp carrier over this many sockets.
	Paths int `toml:"paths"`

	// Preset is the name of the tuning profile.
	Preset string `toml:"preset"`

	// TxQueueLen is how many packets the kernel may hold for the interface.
	TxQueueLen int `toml:"txqueuelen"`

	// Qdisc is the queueing discipline on the interface. Empty takes fq_codel.
	Qdisc string `toml:"qdisc"`

	// AutoMTU measures what the path really carries and sets the interface to match.
	AutoMTU *bool `toml:"auto_mtu"`

	// MSSClamp caps the TCP segment size of connections crossing the tunnel.
	MSSClamp int `toml:"mss_clamp"`

	// Ports are forwarded port mappings served over the tunnel.
	Ports []string `toml:"ports"`

	// AcceptUDP forwards UDP as well as TCP on the mapped ports.
	AcceptUDP bool `toml:"accept_udp"`

	// MaxConnections and BandwidthMbps cap the forwarded ports above.
	MaxConnections int `toml:"max_connections"`
	BandwidthMbps  int `toml:"bandwidth_mbps"`

	// Embedded configs
	SpoofConfig
	PckConfig
}

func (l L3Config) Enabled() bool {
	return strings.TrimSpace(l.Mode) != ""
}

func (l L3Config) AutoMTUEnabled() bool {
	return l.AutoMTU == nil || *l.AutoMTU
}