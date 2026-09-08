package manage

import (
	"fmt"
	"reflect"
	"strconv"
	"strings"

	"github.com/hasan714222-debug/ParsTanel/config"
)

// directSpec is everything the wizard collected for a [direct] tunnel.
type directSpec struct {
	Name             string
	Side             directSide
	Transport        string
	Addr             string
	Token            string
	Ports            []string
	AcceptUDP        bool
	MaxConnections   int
	BandwidthMbps    int
	Sessions         int
	Preset           string
	MuxFrameSize     int
	MuxReceiveBuffer int
	MuxStreamBuffer  int
	Keepalive        int
	Nodelay          bool
	ServerName       string
	ACMEDomain       string
	ACMEEmail        string

	TLSCertFile   string
	TLSKeyFile    string
	MuxVersion    int
	DialTimeout   int
	RetryInterval int
	MSS           int
}

func (s directSpec) render() string {
	var b strings.Builder

	b.WriteString("# Direct tunnel — the Iran server dials out to kharej.\n")
	b.WriteString("# Created by the ParsTanel setup wizard. Both ends must share the token.\n")
	b.WriteString("#\n")
	if s.Side == sideIran {
		b.WriteString("# This is the IRAN side: it exposes the ports and dials out, so it\n")
		b.WriteString("# needs no inbound tunnel port of its own.\n")
	} else {
		b.WriteString("# This is the KHAREJ side: it listens for the tunnel and holds the real\n")
		b.WriteString("# service. It needs no port list — the Iran side names each target.\n")
	}
	b.WriteString("\n[direct]\n")

	writeKV(&b, "role", quote(s.Side.String()))
	writeKV(&b, "addr", quote(s.Addr))
	writeKV(&b, "token", quote(s.Token))
	writeKV(&b, "transport", quote(s.Transport))

	if s.Side == sideIran {
		b.WriteString("\n# Ports exposed on this machine. A target with no host means the\n")
		b.WriteString("# kharej machine's own 127.0.0.1.\n")
		writeKV(&b, "ports", tomlList(s.Ports))
		writeKV(&b, "accept_udp", fmt.Sprint(s.AcceptUDP))
		if s.Sessions > 1 {
			writeKV(&b, "sessions", fmt.Sprint(s.Sessions))
		}
		if s.MaxConnections > 0 || s.BandwidthMbps > 0 {
			b.WriteString("\n# Caps on this tunnel. Zero means unlimited.\n")
			writeKV(&b, "max_connections", fmt.Sprint(s.MaxConnections))
			writeKV(&b, "bandwidth_mbps", fmt.Sprint(s.BandwidthMbps))
		}
		if s.Preset != "" {
			b.WriteString("\n# Performance tuning. The stream buffer is what caps a single\n")
			b.WriteString("# download: at 100 ms round trip it is roughly this many bytes\n")
			b.WriteString("# per RTT. Raise the preset if one transfer feels slow on a fast link.\n")
			writeKV(&b, "preset", quote(s.Preset))
			writeKV(&b, "mux_framesize", fmt.Sprint(s.MuxFrameSize))
			writeKV(&b, "mux_recievebuffer", fmt.Sprint(s.MuxReceiveBuffer))
			writeKV(&b, "mux_streambuffer", fmt.Sprint(s.MuxStreamBuffer))
		}
		if s.Keepalive > 0 {
			writeKV(&b, "keepalive_period", fmt.Sprint(s.Keepalive))
		}
		if s.Nodelay {
			writeKV(&b, "nodelay", "true")
		}
		if s.MSS > 0 {
			writeKV(&b, "mss", fmt.Sprint(s.MSS))
		}
		if s.MuxVersion > 0 {
			writeKV(&b, "mux_version", fmt.Sprint(s.MuxVersion))
		}
		if s.DialTimeout > 0 {
			writeKV(&b, "dial_timeout", fmt.Sprint(s.DialTimeout))
		}
		if s.RetryInterval > 0 {
			writeKV(&b, "retry_interval", fmt.Sprint(s.RetryInterval))
		}
		if s.ServerName != "" {
			b.WriteString("\n# The domain to present in SNI and Host — for a CDN in front of the\n")
			b.WriteString("# kharej server. Setting it also turns certificate checking on.\n")
			writeKV(&b, "server_name", quote(s.ServerName))
		}
	}

	if s.ACMEDomain != "" {
		b.WriteString("\n# A Let's Encrypt certificate, renewed automatically.\n")
		writeKV(&b, "acme_domain", quote(s.ACMEDomain))
		if s.ACMEEmail != "" {
			writeKV(&b, "acme_email", quote(s.ACMEEmail))
		}
	}
	if s.TLSCertFile != "" {
		b.WriteString("\n# A certificate of your own, instead of the generated one.\n")
		writeKV(&b, "tls_cert", quote(s.TLSCertFile))
		writeKV(&b, "tls_key", quote(s.TLSKeyFile))
	}

	return b.String()
}

// l3Spec is everything the wizard collected for an [l3] tunnel.
type l3Spec struct {
	Name           string
	Side           directSide
	Carrier        string
	SNIDomain      string
	Encap          string
	GREKey         uint32
	Addr           string
	Token          string
	Iface          string
	LocalIP        string
	PeerIP         string
	MTU            int
	AutoMTU        *bool
	SockBuf        int
	FECData        int
	FECParity      int
	Paths          int
	MSSClamp       int
	Preset         string
	TxQueueLen     int
	Qdisc          string
	Ports          []string
	AcceptUDP      bool
	MaxConnections int
	BandwidthMbps  int

	Spoof config.SpoofConfig
	Pck   config.PckConfig
}

func (s l3Spec) defaultName() string {
	return "l3-" + s.Side.String() + "-" + addrPort(s.Addr)
}

func (s l3Spec) render() string {
	var b strings.Builder

	b.WriteString("# Full IP tunnel (layer 3) — a private network between the two servers.\n")
	b.WriteString("# Created by the ParsTanel setup wizard. Both ends must share the token,\n")
	b.WriteString("# the carrier, and each other's tunnel addresses.\n")
	b.WriteString("#\n")
	b.WriteString("# Needs root: it creates a TUN network interface.\n")
	b.WriteString("\n[l3]\n")

	mode := "dial"
	if s.Side == sideKharej {
		mode = "listen"
	}
	writeKV(&b, "mode", quote(mode))
	writeKV(&b, "addr", quote(s.Addr))
	writeKV(&b, "token", quote(s.Token))
	writeKV(&b, "carrier", quote(s.Carrier))
	if s.Carrier == "sni" && s.SNIDomain != "" {
		writeKV(&b, "sni_domain", quote(s.SNIDomain))
	}

	writeKV(&b, "encap", quote("gre"))
	if s.GREKey != 0 {
		writeKV(&b, "gre_key", fmt.Sprint(s.GREKey))
	}

	b.WriteString("\n# The two ends of the private network. The other machine has these\n")
	b.WriteString("# two the other way round.\n")
	writeKV(&b, "iface", quote(s.Iface))
	writeKV(&b, "local_ip", quote(s.LocalIP))
	writeKV(&b, "peer_ip", quote(s.PeerIP))
	writeKV(&b, "mtu", fmt.Sprint(s.MTU))
	if s.AutoMTU != nil && !*s.AutoMTU {
		b.WriteString("\n# The tunnel normally measures what the path really carries once it is\n")
		b.WriteString("# up and corrects the mtu above. This turns that off.\n")
		writeKV(&b, "auto_mtu", "false")
	}
	if s.Preset != "" {
		b.WriteString("\n# Performance tuning. The queue is what decides latency under load, and\n")
		b.WriteString("# fq_codel is what keeps a deep queue from becoming latency: it drops\n")
		b.WriteString("# when packets start waiting, so the sender backs off before they do.\n")
		writeKV(&b, "preset", quote(s.Preset))
		writeKV(&b, "txqueuelen", fmt.Sprint(s.TxQueueLen))
		writeKV(&b, "qdisc", quote(s.Qdisc))
	}
	if s.SockBuf > 0 {
		writeKV(&b, "sockbuf", fmt.Sprint(s.SockBuf))
	}
	if s.FECData > 0 && s.FECParity > 0 {
		writeKV(&b, "fec_data", fmt.Sprint(s.FECData))
		writeKV(&b, "fec_parity", fmt.Sprint(s.FECParity))
	}
	if s.Paths > 1 {
		writeKV(&b, "paths", fmt.Sprint(s.Paths))
	}
	if s.MSSClamp != 0 {
		b.WriteString("\n# Caps the segment size of TCP crossing the tunnel. 0 derives it from\n")
		b.WriteString("# the MTU, which is almost always right; -1 turns it off.\n")
		writeKV(&b, "mss_clamp", fmt.Sprint(s.MSSClamp))
	}

	writeSpoofKeys(&b, s.Spoof)
	writePckKeys(&b, s.Pck)

	if len(s.Ports) > 0 {
		b.WriteString("\n# Ports forwarded over the tunnel. Optional: without them the tunnel\n")
		b.WriteString("# simply carries whatever is routed into the interface.\n")
		writeKV(&b, "ports", tomlList(s.Ports))
		writeKV(&b, "accept_udp", fmt.Sprint(s.AcceptUDP))
		if s.MaxConnections > 0 || s.BandwidthMbps > 0 {
			b.WriteString("\n# Caps on the forwarded ports only. Zero means unlimited.\n")
			writeKV(&b, "max_connections", fmt.Sprint(s.MaxConnections))
			writeKV(&b, "bandwidth_mbps", fmt.Sprint(s.BandwidthMbps))
		}
	}

	return b.String()
}

func writeSpoofKeys(b *strings.Builder, s config.SpoofConfig) {
	if reflect.DeepEqual(s, config.SpoofConfig{}) {
		return
	}
	b.WriteString("\n# The forged-source carrier. The peer forges the source of every packet\n")
	b.WriteString("# it sends, so spoof_peer_ip is how this side knows where replies go.\n")

	str := func(key, value string) {
		if value != "" {
			writeKV(b, key, quote(value))
		}
	}
	num := func(key string, value int) {
		if value > 0 {
			writeKV(b, key, fmt.Sprint(value))
		}
	}
	flag := func(key string, value bool) {
		if value {
			writeKV(b, key, "true")
		}
	}

	str("spoof_profile", s.SpoofProfile)
	str("spoof_uplink", s.SpoofUplink)
	str("spoof_downlink", s.SpoofDownlink)
	str("spoof_src_ip", s.SpoofSrcIP)
	if len(s.SpoofSrcPool) > 0 {
		writeKV(b, "spoof_src_pool", tomlList(s.SpoofSrcPool))
	}
	str("spoof_peer_ip", s.SpoofPeerIP)
	str("spoof_dst_ip", s.SpoofDstIP)
	str("spoof_interface", s.SpoofInterface)
	str("spoof_xdp_interface", s.SpoofXDPInterface)
	num("spoof_sockbuf", s.SpoofSockBuf)
	str("spoof_peer_src_ip", s.SpoofPeerSrcIP)
	flag("spoof_icmp_reply", s.SpoofICMPReply)
	num("spoof_mtu", s.SpoofMTU)
	flag("spoof_ttl_jitter", s.SpoofTTLJitter)
	flag("spoof_random_dscp", s.SpoofRandomDSCP)
	flag("spoof_shuffle_port", s.SpoofShufflePort)
	num("spoof_port_min", s.SpoofPortMin)
	num("spoof_port_max", s.SpoofPortMax)
	flag("spoof_padding", s.SpoofPadding)
	num("spoof_padding_max", s.SpoofPaddingMax)
	flag("spoof_fake_tls", s.SpoofFakeTLS)
}

func writePckKeys(b *strings.Builder, p config.PckConfig) {
	if p.PckInterface == "" && p.PckGatewayMAC == "" && len(p.PckFlags) == 0 {
		return
	}
	b.WriteString("\n# The packet-level TCP carrier. Every key is optional: the carrier works\n")
	b.WriteString("# out its own egress from the route to the peer.\n")
	if p.PckInterface != "" {
		writeKV(b, "pck_interface", quote(p.PckInterface))
	}
	if p.PckGatewayMAC != "" {
		writeKV(b, "pck_gateway_mac", quote(p.PckGatewayMAC))
	}
	if len(p.PckFlags) > 0 {
		writeKV(b, "pck_flags", tomlList(p.PckFlags))
	}
}

func directRole(resolved string) string {
	if resolved == "origin" {
		return "kharej"
	}
	return "iran"
}

func l3Role(mode string) string {
	if strings.EqualFold(strings.TrimSpace(mode), "listen") {
		return "kharej"
	}
	return "iran"
}

func HoldsPorts(t Tunnel) bool {
	return t.Role == "server" || t.Role == "iran"
}

func DialsOut(t Tunnel) bool {
	return t.Role == "client" || t.Role == "iran"
}

func IsDirectKind(t Tunnel) bool {
	return strings.HasPrefix(t.Transport, "direct/") || strings.HasPrefix(t.Transport, "l3/")
}

func TunnelDirection(t Tunnel) string {
	if IsDirectKind(t) {
		return "direct"
	}
	return "reverse"
}

func TunnelCarrier(t Tunnel) string {
	if _, rest, found := strings.Cut(t.Transport, "/"); found {
		return rest
	}
	return t.Transport
}

func writeKV(b *strings.Builder, key, value string) {
	fmt.Fprintf(b, "%-12s = %s\n", key, value)
}

func quote(s string) string {
	return strconv.Quote(s)
}

func tomlList(items []string) string {
	quoted := make([]string, len(items))
	for i, item := range items {
		quoted[i] = quote(strings.TrimSpace(item))
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}

func l3EncapLabel(l config.L3Config) string {
	label := "GRE + Noise"
	if l.GREKey != 0 {
		label += fmt.Sprintf(" (key %d)", l.GREKey)
	}
	return label
}

func limitsLabel(maxConns, bandwidthMbps int) string {
	conns := "unlimited"
	if maxConns > 0 {
		conns = fmt.Sprintf("%d connections", maxConns)
	}
	bandwidth := "unlimited"
	if bandwidthMbps > 0 {
		bandwidth = fmt.Sprintf("%d Mbit/s", bandwidthMbps)
	}
	return conns + ", " + bandwidth
}