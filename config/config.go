package config

// TransportType defines the type of transport.
type TransportType string

const (
	TCP     TransportType = "tcp"
	TCPMUX  TransportType = "tcpmux"
	WS      TransportType = "ws"
	WSS     TransportType = "wss"
	WSMUX   TransportType = "wsmux"
	WSSMUX  TransportType = "wssmux"
	UDP     TransportType = "udp"
	KCP     TransportType = "kcp"
	QUIC    TransportType = "quic"
	STEALTH TransportType = "stealth"
	XDI     TransportType = "xdi"
	SPOOF   TransportType = "spoof"
	PCK     TransportType = "pck"
)

// KCPConfig holds the tuning of the KCP transport.
type KCPConfig struct {
	MTU          int  `toml:"kcp_mtu"`
	Interval     int  `toml:"kcp_interval"`
	Resend       int  `toml:"kcp_resend"`
	NoDelay      int  `toml:"kcp_nodelay"`
	NoCongestion int  `toml:"kcp_nocongestion"`
	SndWnd       int  `toml:"kcp_sndwnd"`
	RcvWnd       int  `toml:"kcp_rcvwnd"`
	AckNoDelay   bool `toml:"kcp_acknodelay"`
	DataShards   int  `toml:"kcp_datashards"`
	ParityShards int  `toml:"kcp_parityshards"`
}

// WithDefaults returns a copy with any unset field filled in.
func (k KCPConfig) WithDefaults() KCPConfig {
	if k.DataShards <= 0 || k.ParityShards <= 0 {
		k.DataShards, k.ParityShards = 0, 0
	}
	if k.MTU <= 0 {
		if k.DataShards > 0 {
			k.MTU = 1250
		} else {
			k.MTU = 1350
		}
	}
	if k.Interval <= 0 {
		k.Interval = 20
	}
	if k.Resend < 0 {
		k.Resend = 2
	}
	if k.SndWnd <= 0 {
		k.SndWnd = 1024
	}
	if k.RcvWnd <= 0 {
		k.RcvWnd = 1024
	}
	return k
}

// SpoofConfig holds the IP-spoofing carrier's settings.
type SpoofConfig struct {
	SpoofProfile      string   `toml:"spoof_profile"`
	SpoofUplink       string   `toml:"spoof_uplink"`
	SpoofDownlink     string   `toml:"spoof_downlink"`
	SpoofSrcIP       string   `toml:"spoof_src_ip"`
	SpoofSrcPool      []string `toml:"spoof_src_pool"`
	SpoofPeerIP      string   `toml:"spoof_peer_ip"`
	SpoofDstIP       string   `toml:"spoof_dst_ip"`
	SpoofInterface    string   `toml:"spoof_interface"`
	SpoofXDPInterface string   `toml:"spoof_xdp_interface"`
	SpoofSockBuf      int      `toml:"spoof_sockbuf"`
	SpoofPeerSrcIP    string   `toml:"spoof_peer_src_ip"`
	SpoofICMPReply    bool     `toml:"spoof_icmp_reply"`
	SpoofMTU          int      `toml:"spoof_mtu"`
	SpoofTTLJitter    bool     `toml:"spoof_ttl_jitter"`
	SpoofRandomDSCP   bool     `toml:"spoof_random_dscp"`
	SpoofShufflePort  bool     `toml:"spoof_shuffle_port"`
	SpoofPortMin      int      `toml:"spoof_port_min"`
	SpoofPortMax      int      `toml:"spoof_port_max"`
	SpoofPadding      bool     `toml:"spoof_padding"`
	SpoofPaddingMax   int      `toml:"spoof_padding_max"`
	SpoofFakeTLS      bool     `toml:"spoof_fake_tls"`
}

// PckConfig holds the packet-level TCP carrier's settings.
type PckConfig struct {
	PckInterface  string   `toml:"pck_interface"`
	PckGatewayMAC string   `toml:"pck_gateway_mac"`
	PckFlags      []string `toml:"pck_flags"`
}

// ServerConfig represents the configuration for the server.
type ServerConfig struct {
	BindAddr         string        `toml:"bind_addr"`
	Transport        TransportType `toml:"transport"`
	Token            string        `toml:"token"`
	Nodelay          bool          `toml:"nodelay"`
	Keepalive        int           `toml:"keepalive_period"`
	ChannelSize      int           `toml:"channel_size"`
	LogLevel         string        `toml:"log_level"`
	LogFormat        string        `toml:"log_format"`
	Ports            []string      `toml:"ports"`
	PPROF            bool          `toml:"pprof"`
	MuxSession       int           `toml:"mux_session"`
	MuxVersion       int           `toml:"mux_version"`
	MaxFrameSize     int           `toml:"mux_framesize"`
	MaxReceiveBuffer int           `toml:"mux_recievebuffer"`
	MaxStreamBuffer  int           `toml:"mux_streambuffer"`
	Sniffer          bool          `toml:"sniffer"`
	WebPort          int           `toml:"web_port"`
	WebBind          string        `toml:"web_bind"`
	SnifferLog       string        `toml:"sniffer_log"`
	TLSCertFile      string        `toml:"tls_cert"`
	TLSKeyFile       string        `toml:"tls_key"`
	ACMEDomain       string        `toml:"acme_domain"`
	ACMEEmail        string        `toml:"acme_email"`
	SimpleAuth       bool          `toml:"simple_auth"`
	Heartbeat        int           `toml:"heartbeat"`
	MuxCon           int           `toml:"mux_con"`
	AcceptUDP        *bool         `toml:"accept_udp"`
	SkipOptz         bool          `toml:"skip_optz"`
	MSS              int           `toml:"mss"`
	SO_RCVBUF        int           `toml:"so_rcvbuf"`
	SO_SNDBUF        int           `toml:"so_sndbuf"`
	SOPinTCP         bool          `toml:"so_pin_tcp"`
	ZeroCopy         bool          `toml:"zero_copy"`
	ProxyProtocol    bool          `toml:"proxy_protocol"`
	MaxConnections   int           `toml:"max_connections"`
	BandwidthMbps    int           `toml:"bandwidth_mbps"`
	Preset           string        `toml:"preset"`
	KCPConfig
	PckConfig
}

func (s ServerConfig) ForwardsUDP() bool {
	return s.AcceptUDP != nil && *s.AcceptUDP
}

// ClientConfig represents the configuration for the client.
type ClientConfig struct {
	RemoteAddr       string        `toml:"remote_addr"`
	FallbackAddrs    []string      `toml:"fallback_addrs"`
	Transport        TransportType `toml:"transport"`
	Token            string        `toml:"token"`
	ConnectionPool   int           `toml:"connection_pool"`
	RetryInterval    int           `toml:"retry_interval"`
	Nodelay          bool          `toml:"nodelay"`
	Keepalive        int           `toml:"keepalive_period"`
	LogLevel         string        `toml:"log_level"`
	LogFormat        string        `toml:"log_format"`
	PPROF            bool          `toml:"pprof"`
	MuxSession       int           `toml:"mux_session"`
	MuxVersion       int           `toml:"mux_version"`
	MaxFrameSize     int           `toml:"mux_framesize"`
	MaxReceiveBuffer int           `toml:"mux_recievebuffer"`
	MaxStreamBuffer  int           `toml:"mux_streambuffer"`
	Sniffer          bool          `toml:"sniffer"`
	WebPort          int           `toml:"web_port"`
	WebBind          string        `toml:"web_bind"`
	SnifferLog       string        `toml:"sniffer_log"`
	DialTimeout      int           `toml:"dial_timeout"`
	AggressivePool   bool          `toml:"aggressive_pool"`
	EdgeIP           string        `toml:"edge_ip"`
	SimpleAuth       bool          `toml:"simple_auth"`
	SkipOptz         bool          `toml:"skip_optz"`
	MSS              int           `toml:"mss"`
	SO_RCVBUF        int           `toml:"so_rcvbuf"`
	SO_SNDBUF        int           `toml:"so_sndbuf"`
	Proxy            string        `toml:"proxy"`
	LocalAddr        string        `toml:"local_addr"`
	Interface        string        `toml:"interface"`
	SOMark           int           `toml:"so_mark"`
	SOPinTCP         bool          `toml:"so_pin_tcp"`
	ZeroCopy         bool          `toml:"zero_copy"`
	Preset           string        `toml:"preset"`
	LoadBalance      bool          `toml:"load_balance"`
	HealthFailover   bool          `toml:"health_failover"`
	KCPConfig
	PckConfig
}

// Config represents the complete configuration.
type Config struct {
	Server ServerConfig `toml:"server"`
	Client ClientConfig `toml:"client"`
	L3     L3Config     `toml:"l3"`
	Direct DirectConfig `toml:"direct"`
}