package manage

import (
	"fmt"
	"net"
	"strings"

	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/optimize"
	"github.com/hasan714222-debug/ParsTanel/internal/tui"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"
)

type transportEntry struct {
	label, desc, value string
}

var transportGroups = []struct {
	label, desc string
	entries     []transportEntry
}{
	{"TCP", "reliable and simple — the safe default", []transportEntry{
		{"TCP", "plain & fast — start here if unsure", "tcp"},
		{"TCP Mux", "many streams over few connections — multiplexed", "tcpmux"},
		{"TCP + Stealth", "encrypted with no fingerprint — hardest to detect, for heavy filtering", "stealth"},
		{"TCP + PCK", "builds its own TCP packets, below the kernel — for a path where a normal TCP flow is reset or throttled; Linux, needs root", "pck"},
	}},
	{"UDP", "lower latency, better on lossy or throttled links", []transportEntry{
		{"UDP", "raw datagrams — for UDP-based services", "udp"},
		{"UDP + KCP + FEC", "low-latency gaming tunnel — reliable UDP with always-on error correction", "kcp"},
		{"UDP + QUIC", "encrypted TLS 1.3 streams over UDP — self-tuning, great under loss", "quic"},
	}},
	{"WebSocket", "looks like normal web traffic — CDN friendly", []transportEntry{
		{"WS", "WebSocket — HTTP camouflage, CDN friendly", "ws"},
		{"WS Mux", "WebSocket — multiplexed", "wsmux"},
		{"WSS", "secure WebSocket — TLS encrypted", "wss"},
		{"WSS Mux", "TLS WebSocket — multiplexed", "wssmux"},
	}},
}

func chooseTransport() string {
	for {
		groupOpts := make([]tui.Option, len(transportGroups))
		for i, g := range transportGroups {
			groupOpts[i] = tui.Option{Title: g.label, Desc: g.desc}
		}
		gi := tui.ChooseOpt("Select transport family:", groupOpts)
		if gi < 0 {
			return ""
		}
		group := transportGroups[gi]

		entryOpts := make([]tui.Option, len(group.entries))
		for i, e := range group.entries {
			entryOpts[i] = tui.Option{Title: e.label, Desc: e.desc}
		}
		ei := tui.ChooseOpt("Select "+group.label+" transport:", entryOpts)
		if ei < 0 {
			continue
		}
		if group.entries[ei].value == "" {
			tui.Warn(group.entries[ei].label + " is not available yet — please pick another transport.")
			tui.PressEnter()
			continue
		}
		return group.entries[ei].value
	}
}

func choosePreset(transport string) string {
	options := presetOptionsFor(transport)
	opts := make([]tui.Option, len(options))
	for i, o := range options {
		opts[i] = tui.Option{Title: o.label, Desc: o.desc}
	}
	idx := tui.ChooseOpt("Performance preset:", opts)
	if idx < 0 {
		return PresetTurbo
	}
	return options[idx].value
}

func applyManualTuning(s *TunnelSpec) {
	s.Nodelay = tui.Confirm("Enable TCP_NODELAY (lower latency)", s.Nodelay)
	s.KeepAlive = tui.PromptInt("Keepalive period (seconds)", s.KeepAlive)
	s.Heartbeat = tui.PromptInt("Heartbeat interval (seconds, 0 to disable)", s.Heartbeat)
	s.LogLevel = tui.PromptDefault("Log level (info/debug/warn/error)", s.LogLevel)
	if tui.Confirm("Write logs as JSON (for log collectors and scripts)", s.LogFormat == "json") {
		s.LogFormat = "json"
	} else {
		s.LogFormat = ""
	}
	if s.Role == "server" {
		s.ChannelSize = tui.PromptInt("Channel size", s.ChannelSize)
	} else {
		s.ConnectionPool = tui.PromptInt("Connection pool size", s.ConnectionPool)
		s.AggressivePool = tui.Confirm("Enable aggressive pool", s.AggressivePool)
	}
	if !isDatagram(s.Transport) {
		tui.Warn("MSS caps the largest TCP segment the tunnel sends. Keep it at 0")
		tui.Warn("unless Diagnose reports that the path cannot carry full-sized")
		tui.Warn("packets — it prints the value, and both ends need the same one.")
		s.MSS = tui.PromptInt("TCP MSS clamp (bytes, 0 = automatic)", s.MSS)
	}
	if isMux(s.Transport) {
		s.MuxCon = tui.PromptInt("Mux connections/sessions", s.MuxCon)
		s.MuxVersion = tui.PromptInt("Mux version (1 or 2)", s.MuxVersion)
		s.MuxFrameSize = tui.PromptInt("Mux frame size", s.MuxFrameSize)
		s.MuxRecvBuffer = tui.PromptInt("Mux receive buffer", s.MuxRecvBuffer)
		s.MuxStreamBuffer = tui.PromptInt("Mux stream buffer", s.MuxStreamBuffer)
	}
	if isKCP(s.Transport) {
		s.KCPMTU = tui.PromptInt("KCP MTU (bytes, keep below the path MTU)", s.KCPMTU)
		s.KCPInterval = tui.PromptInt("KCP interval (ms — lower reacts faster, costs CPU)", s.KCPInterval)
		s.KCPSndWnd = tui.PromptInt("KCP send window (packets)", s.KCPSndWnd)
		s.KCPRcvWnd = tui.PromptInt("KCP receive window (packets)", s.KCPRcvWnd)
		s.KCPDataShards = tui.PromptInt("FEC data shards (0 disables error correction)", s.KCPDataShards)
		s.KCPParityShards = tui.PromptInt("FEC parity shards (losses repaired per group)", s.KCPParityShards)
	}
	if s.Transport == "tcp" {
		tui.Warn("Zero-copy hands forwarded traffic straight to the kernel. It is the")
		tui.Warn("fastest path and the least proven one — try it on a spare tunnel")
		tui.Warn("before a busy one. Nothing about it reaches the wire, so the two")
		tui.Warn("ends need not agree.")
		s.ZeroCopy = tui.Confirm("Enable zero-copy forwarding (experimental)", s.ZeroCopy)
	}

	s.Preset = ""
}

func setupServerTLS(s *TunnelSpec) bool {
	tui.Info("WSS transports need a TLS certificate.")
	fmt.Println()
	tui.Warn("Self-signed encrypts exactly as well — the client is ParsTanel's own")
	tui.Warn("code and does not verify it. A real certificate matters for how the")
	tui.Warn("connection looks from outside: real HTTPS on 443 is never self-signed,")
	tui.Warn("so a self-signed one stands out. It is also what a CDN requires.")
	fmt.Println()

	choice := tui.ChooseOpt("TLS certificate:", []tui.Option{
		{Title: "Self-signed, generated now", Desc: "works anywhere, including on a bare IP — the default"},
		{Title: "Let's Encrypt, automatic", Desc: "free and real — needs a domain pointing at this server"},
		{Title: "Use existing certificate/key files", Desc: "a certificate you already have on disk"},
	})

	switch choice {
	case 0:
		host := strings.TrimSpace(tui.PromptDefault("Domain or IP to embed in the cert (optional)", ""))
		return generateSelfSigned(s, host)

	case 1:
		if p := addrPort(s.BindAddr); p != "443" {
			tui.Warn("This tunnel is on port " + p + ", not 443.")
			tui.Warn("Let's Encrypt will have to validate over port 80 instead, so")
			tui.Warn("port 80 must be free on this server and open in the firewall.")
			fmt.Println()
		}

		domain, email, ok := promptACMEDomain("", "")
		if !ok {
			return false
		}
		s.ACMEDomain, s.ACMEEmail = domain, email
		if !generateSelfSigned(s, domain) {
			return false
		}
		fmt.Println()
		tui.Success("Let's Encrypt will be used for " + domain + ".")
		tui.Warn("The certificate is requested on the first connection. If it does")
		tui.Warn("not arrive, the tunnel keeps working on the self-signed one —")
		tui.Warn("check: journalctl -u " + app.ServiceName(s.Name) + " -n 50")
		return true

	case 2:
		s.TLSCert = strings.TrimSpace(tui.Prompt("Path to TLS certificate: "))
		s.TLSKey = strings.TrimSpace(tui.Prompt("Path to TLS key: "))
		if err := validCertPair(s.TLSCert, s.TLSKey); err != nil {
			tui.Error("Invalid certificate: " + err.Error())
			tui.PressEnter()
			return false
		}
		return true

	default:
		return false
	}
}

func generateSelfSigned(s *TunnelSpec, host string) bool {
	cert, key, err := EnsureSelfSignedCert(s.Name, host)
	if err != nil {
		tui.Error("Certificate generation failed: " + err.Error())
		tui.PressEnter()
		return false
	}
	s.TLSCert, s.TLSKey = cert, key
	return true
}

func promptACMEDomain(currentDomain, currentEmail string) (domain, email string, ok bool) {
	fmt.Println()
	tui.Warn("Requirements, all of them:")
	tui.Warn("  • a domain whose A record points at this server's IP")
	tui.Warn("  • port 80 reachable from outside, OR this tunnel on port 443")
	tui.Warn("  • this server able to reach acme-v02.api.letsencrypt.org")
	fmt.Println()

	domain = strings.TrimSpace(tui.PromptDefault("Domain", currentDomain))
	if domain == "" {
		tui.Error("A domain is required.")
		tui.PressEnter()
		return "", "", false
	}
	if net.ParseIP(domain) != nil {
		tui.Error("That is an IP address. Let's Encrypt only issues for domain names.")
		tui.PressEnter()
		return "", "", false
	}

	if ips, err := net.LookupHost(domain); err != nil {
		tui.Error("That domain does not resolve: " + err.Error())
		if !tui.Confirm("Use it anyway", false) {
			return "", "", false
		}
	} else {
		tui.Info("Resolves to: " + strings.Join(ips, ", "))
		if mine := PublicIPv4(); mine != "" && mine != "-" && !contains(ips, mine) {
			tui.Error("None of those is this server's address (" + mine + ").")
			tui.Warn("Let's Encrypt validates by connecting to the domain, so it would")
			tui.Warn("reach a different machine and issuance would fail.")
			if !tui.Confirm("Use it anyway", false) {
				return "", "", false
			}
		}
	}

	email = strings.TrimSpace(tui.PromptDefault("Email for expiry warnings (optional)", currentEmail))
	return domain, email, true
}

func askPck(s *TunnelSpec) {
	if s.Transport != "pck" {
		return
	}
	fmt.Println()
	tui.Warn("TCP + PCK builds and reads its own TCP packets instead of using the")
	tui.Warn("kernel's TCP stack. Nothing is forged — the address and ports are")
	tui.Warn("real — but no socket, no handshake and no connection state exist, so")
	tui.Warn("connection tracking and netfilter have nothing to act on.")
	tui.Warn("Linux only, needs root, and BOTH ends must be on this transport.")
	fmt.Println()
	tui.Info("The interface, local address and next hop are read from this machine's")
	tui.Info("own routing table — there is nothing to enter for them.")
	fmt.Println()

	opts := network.SuggestedTCPFlagCycles()
	menu := make([]tui.Option, len(opts))
	for i, o := range opts {
		menu[i] = tui.Option{Title: o.Value, Desc: o.Desc}
	}
	if i := tui.ChooseOpt("Flag pattern:", menu); i > 0 {
		s.PckFlags = strings.Split(opts[i].Value, ",")
	} else {
		s.PckFlags = nil
	}

	fmt.Println()
	if tui.Confirm("Override the automatic interface / gateway detection", false) {
		tui.Warn("Leave either empty to keep the automatic answer for it.")
		if names := routableInterfaces(); len(names) > 0 {
			tui.Info("Interfaces: " + strings.Join(names, ", "))
		}
		for {
			raw := strings.TrimSpace(tui.PromptDefault("Interface", ""))
			if raw == "" {
				break
			}
			if _, err := net.InterfaceByName(raw); err != nil {
				tui.Error(fmt.Sprintf("no such interface: %v", err))
				continue
			}
			s.PckInterface = raw
			break
		}
		for {
			raw := strings.TrimSpace(tui.PromptDefault("Gateway MAC", ""))
			if raw == "" {
				break
			}
			if _, err := net.ParseMAC(raw); err != nil {
				tui.Error(fmt.Sprintf("not a MAC address: %v", err))
				continue
			}
			s.PckGatewayMAC = raw
			break
		}
	}
}

func askProxyProtocol(s *TunnelSpec) {
	if !supportsProxyProtocol(s.Transport) {
		return
	}
	fmt.Println()
	tui.Info("Send the real client IP to the service behind the tunnel?")
	tui.Warn("Without this, your panel sees every user coming from one address, so")
	tui.Warn("per-user device/IP limits cannot work. With it, each connection")
	tui.Warn("carries a PROXY protocol v2 header holding the real client IP.")
	fmt.Println()
	tui.Error("Only turn this on if the service is set to ACCEPT the PROXY protocol.")
	tui.Error("If it is not, it will read the header as data and every connection breaks.")
	tui.Warn("In X-UI / Marzban this is the inbound option named \"Accept Proxy Protocol\".")
	fmt.Println()
	s.ProxyProtocol = tui.Confirm("Enable PROXY protocol (send real client IP)", false)
}

func uniqueName(name string) string {
	for {
		switch {
		case !validName(name):
			tui.Warn(fmt.Sprintf("Invalid name %q — use letters, digits, dots, dashes (max 40).", name))
		case fileExists(app.ConfigPath(name)):
			tui.Warn(fmt.Sprintf("A tunnel named %q already exists.", name))
		default:
			return name
		}
		name = tui.Prompt("Choose a different name: ")
	}
}

func SetupServer() {
	tui.Clear()
	tui.Title("Setup Server")
	tui.Warn("Iran side — reverse tunnel that exposes ports on this machine.")
	fmt.Println()

	transport := chooseTransport()
	if transport == "" {
		return
	}

	s := TunnelSpec{Role: "server", Transport: transport, AcceptUDP: false}

	port := tui.Prompt("Tunnel (control) port: ")
	if !validPort(port) {
		tui.Error("Invalid port.")
		tui.PressEnter()
		return
	}
	bind := "0.0.0.0"
	if tui.Confirm("Listen on IPv6 as well", false) {
		bind = "::"
	}
	s.BindAddr = net.JoinHostPort(bind, port)

	defaultName := "server-" + port
	s.Name = uniqueName(tui.PromptDefault("Tunnel name", defaultName))

	suggested := randomToken(64)
	tui.Info("Suggested 64-char token (press Enter to accept — copy it to the client):")
	fmt.Println("  " + tui.Color(tui.Bold+tui.White, suggested))
	s.Token = tui.PromptDefault("Security token", suggested)

	fmt.Println()
	tui.Warn("A bare port (443) means: expose 443 here, and the KHAREJ server")
	tui.Warn("forwards it to its own 127.0.0.1:443 — so your panel must listen")
	tui.Warn("on that exact port there.")
	tui.Warn("If the service is elsewhere, say so: 443=127.0.0.1:2096")
	tui.Warn("Several backends for one port: 443=127.0.0.1:2096|127.0.0.1:2097")
	tui.Warn("(separated by |, checked continuously, balanced over the live ones)")
	fmt.Println()

	portsRaw := tui.Prompt("Exposed ports (comma separated, e.g. 443,8080 or 443=1.1.1.1:443): ")
	s.Ports = parsePorts(portsRaw)
	if len(s.Ports) == 0 {
		tui.Error("No valid ports entered.")
		tui.PressEnter()
		return
	}
	if err := validatePortSpecs(s.Ports); err != nil {
		tui.Error(err.Error())
		tui.PressEnter()
		return
	}

	fmt.Println()
	tui.Warn("UDP forwarding is OFF by default. Say yes for Xray/Shadowsocks UDP,")
	tui.Warn("WireGuard, DNS or games. Say no for a plain web or proxy tunnel.")
	s.AcceptUDP = tui.Confirm("Carry UDP as well as TCP on the exposed ports", false)

	showForwardTargets(s.Ports, s.AcceptUDP)

	if needsTLS(transport) && !setupServerTLS(&s) {
		return
	}
	askSimpleAuth(&s, transport)
	askPck(&s)
	askProxyProtocol(&s)

	ApplyPreset(&s, choosePreset(s.Transport))
	if tui.Confirm("Fine-tune the advanced settings by hand", false) {
		applyManualTuning(&s)
	}

	finishSetup(s)
}

func SetupClient() {
	tui.Clear()
	tui.Title("Setup Client")
	tui.Warn("Kharej side — reverse tunnel that dials out to the Iran server.")
	fmt.Println()

	transport := chooseTransport()
	if transport == "" {
		return
	}

	s := TunnelSpec{Role: "client", Transport: transport}

	remoteHost := tui.Prompt("Server address (IP or domain of the server): ")
	remotePort := tui.Prompt("Server tunnel port: ")
	if remoteHost == "" || !validPort(remotePort) {
		tui.Error("Invalid server address or port.")
		tui.PressEnter()
		return
	}
	s.RemoteAddr = net.JoinHostPort(strings.Trim(remoteHost, "[]"), remotePort)

	if !checkServerAddress(strings.Trim(remoteHost, "[]"), transport, remotePort) {
		return
	}

	defaultName := "client-" + remotePort
	s.Name = uniqueName(tui.PromptDefault("Tunnel name", defaultName))

	tui.Info("Enter the SAME token you configured on the server.")
	s.Token = tui.PromptDefault("Security token", "parstanel")

	if isWS(transport) {
		tui.Info("Optional edge IP: connect to a CDN edge (e.g. Cloudflare) instead of")
		tui.Info("resolving the server address directly. Leave empty to skip.")
		s.EdgeIP = strings.TrimSpace(tui.PromptDefault("Edge IP", ""))
	}
	askSimpleAuth(&s, transport)
	askPck(&s)

	fmt.Println()
	if tui.Confirm("Configure optional connection settings (proxy, interface, backup addresses)", false) {
		if !isDatagram(transport) {
			fmt.Println()
			tui.Info("Optional proxy: reach the tunnel server through a SOCKS5 or HTTP proxy.")
			for {
				raw := strings.TrimSpace(tui.PromptDefault("Proxy URL", ""))
				if raw == "" {
					break
				}
				if _, err := network.ParseProxy(raw); err != nil {
					tui.Error(fmt.Sprintf("%v", err))
					continue
				}
				s.Proxy = raw
				break
			}

			if names := routableInterfaces(); len(names) > 1 {
				fmt.Println()
				tui.Info("Available: " + strings.Join(names, ", ") + " — leave empty to let the kernel decide.")
				for {
					raw := strings.TrimSpace(tui.PromptDefault("Interface", ""))
					if raw == "" {
						break
					}
					if _, err := net.InterfaceByName(raw); err != nil {
						tui.Error(fmt.Sprintf("no such interface: %v", err))
						continue
					}
					s.Interface = raw
					break
				}
				s.LocalAddr = strings.TrimSpace(tui.PromptDefault("Source address (optional)", ""))
			}
		}

		fmt.Println()
		tui.Info("Optional backup server addresses — comma separated.")
		if raw := strings.TrimSpace(tui.PromptDefault("Backup addresses", "")); raw != "" {
			for _, part := range strings.Split(raw, ",") {
				part = strings.TrimSpace(part)
				if part == "" {
					continue
				}
				if _, _, err := net.SplitHostPort(part); err != nil {
					part = net.JoinHostPort(strings.Trim(part, "[]"), remotePort)
				}
				s.FallbackAddrs = append(s.FallbackAddrs, part)
			}
		}
		if len(s.FallbackAddrs) > 0 {
			fmt.Println()
			tui.Info("Automatic failover scores every address and keeps traffic on the healthiest.")
			if tui.Confirm("Enable automatic failover to the healthiest server", false) {
				s.HealthFailover = true
			} else {
				s.LoadBalance = tui.Confirm("Enable load balancing", false)
			}
		}
	}

	ApplyPreset(&s, choosePreset(s.Transport))
	if tui.Confirm("Fine-tune the advanced settings by hand", false) {
		applyManualTuning(&s)
	}

	finishSetup(s)
}

func finishSetup(s TunnelSpec) {
	addr := s.BindAddr
	if s.Role == "client" {
		addr = s.RemoteAddr
	}
	if why := portClash(s.Role, addr, s.Name); why != "" {
		fmt.Println()
		tui.Error(why)
		fmt.Println()
		tui.Info("Nothing was written. Run setup again with a different port.")
		tui.PressEnter()
		return
	}

	tui.Info("Applying system network optimizations...")
	optimize.ApplyQuiet()

	service, err := s.Save()
	if err != nil {
		tui.Error("Failed to create tunnel: " + err.Error())
		tui.PressEnter()
		return
	}

	fmt.Println()
	if IsActive(service) {
		tui.Success(fmt.Sprintf("Tunnel %q is up and running (%s).", s.Name, service))
	} else {
		tui.Warn(fmt.Sprintf("Tunnel %q created but not active yet — check logs.", s.Name))
	}
	tui.PressEnter()
}

func showForwardTargets(ports []string, acceptUDP bool) {
	type target struct{ exposed, dest string }
	var targets []target

	for _, p := range ports {
		p = strings.TrimSpace(p)
		exposed, dest, found := strings.Cut(p, "=")
		exposed = strings.TrimSpace(exposed)
		if !found {
			dest = "127.0.0.1:" + exposed
		} else {
			var parts []string
			for _, d := range strings.Split(strings.TrimSpace(dest), "|") {
				d = strings.TrimSpace(d)
				if d == "" {
					continue
				}
				if !strings.Contains(d, ":") {
					d = "127.0.0.1:" + d
				}
				parts = append(parts, d)
			}
			dest = strings.Join(parts, "  |  ")
		}
		targets = append(targets, target{exposed, dest})
	}
	if len(targets) == 0 {
		return
	}

	fmt.Println()
	tui.Info("On the KHAREJ server, these must be listening:")
	for _, t := range targets {
		fmt.Printf("  %s%s%s  →  %s%s%s\n",
			tui.Gray, t.exposed, tui.Reset,
			tui.Bold+tui.White, t.dest, tui.Reset)
	}
	fmt.Println()
	tui.Warn("Check there with:  ss -tlnp | grep <port>")
	tui.Warn("A panel bound to a public IP instead of 127.0.0.1 will refuse the connection.")
	fmt.Println()
	if acceptUDP {
		tui.Info("These ports carry UDP as well as TCP.")
		tui.Warn("Open BOTH in the firewall here:  ufw allow <port>/tcp && ufw allow <port>/udp")
	} else {
		tui.Info("These ports carry TCP only — UDP forwarding is off.")
		tui.Warn("Open them in the firewall here:  ufw allow <port>/tcp")
	}
	fmt.Println()
}

func checkServerAddress(host, transport, port string) bool {
	if host == "" || net.ParseIP(host) != nil {
		return true
	}

	ips, err := net.LookupHost(host)
	if err != nil {
		tui.Error("That domain does not resolve: " + err.Error())
		return tui.Confirm("Use it anyway", false)
	}

	v4, v6 := splitFamilies(ips)

	fmt.Println()
	if len(v4) > 0 {
		tui.Info(host + " → IPv4: " + strings.Join(v4, ", "))
	}
	if len(v6) > 0 {
		tui.Info(host + " → IPv6: " + strings.Join(v6, ", "))
	}

	cdn := detectCDN(ips)
	if cdn == "" {
		if len(v6) > 0 && len(v4) > 0 {
			tui.Error("This domain has both IPv4 and IPv6 addresses.")
			tui.Warn("If a bare IP works and this domain does not, that is almost certainly why.")
			fmt.Println()
			return tui.Confirm("Continue with this address", false)
		}
		return tui.Confirm("Continue with this address", true)
	}

	tui.Error("That address belongs to " + cdn + ", not to a server.")
	fmt.Println()
	if isWS(transport) && cdnPort(port) {
		tui.Warn("A WebSocket tunnel can go through a CDN.")
	} else {
		tui.Error("This will not work for raw protocols.")
	}
	fmt.Println()
	return tui.Confirm("Continue anyway", false)
}

var cloudflareRanges = []string{
	"173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
	"141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
	"197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
	"104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
}

var otherCDNNames = map[string]string{
	"cloudfront": "CloudFront",
	"akamai":     "Akamai",
	"fastly":     "Fastly",
	"gcore":      "Gcore",
	"arvancloud": "ArvanCloud",
	"derak":      "Derak Cloud",
}

func detectCDN(ips []string) string {
	for _, raw := range ips {
		ip := net.ParseIP(raw)
		if ip == nil {
			continue
		}
		for _, cidr := range cloudflareRanges {
			_, network, err := net.ParseCIDR(cidr)
			if err == nil && network.Contains(ip) {
				return "Cloudflare"
			}
		}
	}
	for _, raw := range ips {
		names, err := net.LookupAddr(raw)
		if err != nil {
			continue
		}
		for _, n := range names {
			n = strings.ToLower(n)
			for needle, label := range otherCDNNames {
				if strings.Contains(n, needle) {
					return label
				}
			}
		}
	}
	return ""
}
func spoofStealthOn(sc config.SpoofConfig) bool {
	return sc.SpoofPadding || sc.SpoofFakeTLS
}

func applySpoofStealth(sc *config.SpoofConfig) {
	sc.SpoofPadding = true
	if sc.SpoofPaddingMax <= 0 {
		sc.SpoofPaddingMax = 64
	}
	sc.SpoofTTLJitter = true
	sc.SpoofRandomDSCP = true
	sc.SpoofShufflePort = true
	if sc.SpoofPortMin <= 0 {
		sc.SpoofPortMin = 49152
	}
	if sc.SpoofPortMax <= sc.SpoofPortMin {
		sc.SpoofPortMax = 65535
	}
	up, down := network.ResolveSpoofDirections(sc.SpoofProfile, sc.SpoofUplink, sc.SpoofDownlink)
	sc.SpoofFakeTLS = (up == "tcp" || down == "tcp")
}

func askSpoofCarrier(sc *config.SpoofConfig, onIran bool) {
	fmt.Println()
	tui.Title("IP Spoofing Carrier")
	tui.Info("The carrier forges the source address on each packet.")
	fmt.Println()

	profile := "udp"
	if !tui.Confirm("Use UDP — the recommended packet profile", true) {
		idx := tui.ChooseOpt("Select packet profile:", []tui.Option{
			{Title: "udp", Desc: "plain datagrams (default)"},
			{Title: "icmp", Desc: "echo requests (ping)"},
			{Title: "tcp", Desc: "TCP SYN flow"},
			{Title: "icmpv6", Desc: "ICMPv6 echo inside IPv4 proto 58"},
			{Title: "proto58", Desc: "bare protocol 58"},
			{Title: "ipip", Desc: "IP-in-IP encapsulation (proto 4)"},
			{Title: "gre", Desc: "GRE encapsulation (proto 47)"},
		})
		switch idx {
		case 1:
			profile = "icmp"
		case 2:
			profile = "tcp"
		case 3:
			profile = "icmpv6"
		case 4:
			profile = "proto58"
		case 5:
			profile = "ipip"
		case 6:
			profile = "gre"
		default:
			profile = "udp"
		}
	}
	sc.SpoofProfile = profile

	if tui.Confirm("Set the two directions separately", false) {
		sc.SpoofUplink = tui.PromptDefault("Uplink profile (client->server)", profile)
		sc.SpoofDownlink = tui.PromptDefault("Downlink profile (server->client)", profile)
	}

	if !onIran {
		fmt.Println()
		tui.Warn("The Iran server forges its packets, so its real IP cannot be learned from them.")
		sc.SpoofPeerIP = strings.TrimSpace(tui.Prompt("Real IPv4 of the Iran server: "))
	}

	fmt.Println()
	tui.Info("Forged source IPv4 (leave blank to run unforged first):")
	src := strings.TrimSpace(tui.Prompt("Forged source IPv4: "))
	if src != "" {
		if strings.Contains(src, ",") {
			parts := strings.Split(src, ",")
			sc.SpoofSrcPool = nil
			for _, p := range parts {
				if p = strings.TrimSpace(p); p != "" {
					sc.SpoofSrcPool = append(sc.SpoofSrcPool, p)
				}
			}
			if len(sc.SpoofSrcPool) > 0 {
				sc.SpoofSrcIP = sc.SpoofSrcPool[0]
			}
		} else {
			sc.SpoofSrcIP = src
			sc.SpoofSrcPool = []string{src}
		}
	}

	if tui.Confirm("Turn Stealth on (padding and header cosmetics)", false) {
		applySpoofStealth(sc)
	} else {
		clearSpoofStealth(sc)
	}
}
func cdnPort(port string) bool {
	switch port {
	case "443", "2053", "2083", "2087", "2096", "8443",
		"80", "8080", "8880", "2052", "2082", "2086", "2095":
		return true
	}
	return false
}

func splitFamilies(ips []string) (v4, v6 []string) {
	for _, raw := range ips {
		ip := net.ParseIP(raw)
		if ip == nil {
			continue
		}
		if ip.To4() != nil {
			v4 = append(v4, raw)
		} else {
			v6 = append(v6, raw)
		}
	}
	return v4, v6
}

func routableInterfaces() []string {
	ifaces, err := net.Interfaces()
	if err != nil {
		return nil
	}
	var names []string
	for _, ifi := range ifaces {
		if ifi.Flags&net.FlagUp == 0 || ifi.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs, err := ifi.Addrs()
		if err != nil || len(addrs) == 0 {
			continue
		}
		names = append(names, ifi.Name)
	}
	return names
}

func askSimpleAuth(s *TunnelSpec, transport string) {
	if !needsTLS(transport) {
		return
	}
	fmt.Println()
	tui.Info("If a reverse proxy terminates TLS in front of this tunnel, simple auth sends the raw token.")
	s.SimpleAuth = tui.Confirm("Use simple token auth", s.SimpleAuth)
}

func clearSpoofStealth(sc *config.SpoofConfig) {
	sc.SpoofPadding, sc.SpoofPaddingMax = false, 0
	sc.SpoofTTLJitter = false
	sc.SpoofRandomDSCP = false
	sc.SpoofShufflePort = false
	sc.SpoofPortMin, sc.SpoofPortMax = 0, 0
	sc.SpoofFakeTLS = false
}
