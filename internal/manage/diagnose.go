package manage

import (
	"fmt"
	"math"
	"net"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"
)

type CheckLevel int

const (
	CheckOK CheckLevel = iota
	CheckWarn
	CheckFail
	CheckInfo
)

type Check struct {
	Group  string
	Name   string
	Level  CheckLevel
	Detail string
	Fix    string
}

func Diagnose() []Check {
	var out []Check
	out = append(out, systemChecks()...)
	out = append(out, monitorChecks()...)
	out = append(out, tunnelChecks()...)
	return out
}

func CountByLevel(checks []Check) (ok, warn, fail int) {
	for _, c := range checks {
		switch c.Level {
		case CheckOK:
			ok++
		case CheckWarn:
			warn++
		case CheckFail:
			fail++
		}
	}
	return
}

func systemChecks() []Check {
	const g = "System"
	var out []Check

	out = append(out, Check{Group: g, Name: "ParsTanel version", Level: CheckInfo, Detail: app.Version})

	if fi, err := os.Stat(app.BinPath); err == nil {
		lvl, fix := CheckOK, ""
		if fi.Mode().Perm()&0111 == 0 {
			lvl, fix = CheckFail, "chmod +x "+app.BinPath
		}
		out = append(out, Check{Group: g, Name: "Binary", Level: lvl, Detail: app.BinPath, Fix: fix})
	} else {
		out = append(out, Check{Group: g, Name: "Binary", Level: CheckFail,
			Detail: "missing at " + app.BinPath, Fix: "reinstall ParsTanel"})
	}

	if os.Geteuid() == 0 {
		out = append(out, Check{Group: g, Name: "Root privileges", Level: CheckOK, Detail: "running as root"})
	} else {
		out = append(out, Check{Group: g, Name: "Root privileges", Level: CheckFail,
			Detail: "not root", Fix: "run: sudo parstanel"})
	}

	if _, err := exec.LookPath("systemctl"); err == nil {
		out = append(out, Check{Group: g, Name: "systemd", Level: CheckOK, Detail: "available"})
	} else {
		out = append(out, Check{Group: g, Name: "systemd", Level: CheckFail,
			Detail: "systemctl not found", Fix: "ParsTanel needs systemd to manage services"})
	}

	if runtime.GOOS != "linux" {
		out = append(out, Check{Group: g, Name: "Platform", Level: CheckWarn,
			Detail: runtime.GOOS, Fix: "ParsTanel is designed for Linux servers"})
		return out
	}

	if v := sysctlValue("net.ipv4.tcp_congestion_control"); v != "" {
		if v == "bbr" {
			out = append(out, Check{Group: g, Name: "Congestion control", Level: CheckOK, Detail: "bbr"})
		} else {
			out = append(out, Check{Group: g, Name: "Congestion control", Level: CheckWarn,
				Detail: v + " (bbr gives better throughput)", Fix: "run Optimize from the main menu"})
		}
	}
	if v := sysctlValue("net.core.default_qdisc"); v != "" && v != "fq" {
		out = append(out, Check{Group: g, Name: "Queue discipline", Level: CheckWarn,
			Detail: v + " (fq pairs with bbr)", Fix: "run Optimize from the main menu"})
	}
	if v := sysctlValue("net.core.rmem_max"); v != "" {
		n, _ := strconv.Atoi(v)
		if n >= 16*1024*1024 {
			out = append(out, Check{Group: g, Name: "Socket buffers", Level: CheckOK, Detail: humanSize(n) + " max"})
		} else {
			out = append(out, Check{Group: g, Name: "Socket buffers", Level: CheckWarn,
				Detail: humanSize(n) + " max — small for high-latency links",
				Fix:    "run Optimize from the main menu"})
		}
	}
	if v := sysctlValue("net.ipv4.ip_forward"); v == "0" {
		out = append(out, Check{Group: g, Name: "IP forwarding", Level: CheckWarn,
			Detail: "disabled", Fix: "run Optimize (needed for some forwarding setups)"})
	}

	if v, where := nofileForTunnels(); v > 0 {
		if v >= 65536 {
			out = append(out, Check{Group: g, Name: "Open file limit", Level: CheckOK,
				Detail: strconv.Itoa(v) + " " + where})
		} else {
			out = append(out, Check{Group: g, Name: "Open file limit", Level: CheckWarn,
				Detail: strconv.Itoa(v) + " " + where + " — low for many connections",
				Fix:    "restart this tunnel — its unit has been brought up to date; the ceiling comes from the unit, not from Optimize"})
		}
	}

	out = append(out, Check{Group: g, Name: "System time", Level: CheckInfo,
		Detail: time.Now().Format("2006-01-02 15:04:05 MST")})

	return out
}

func monitorChecks() []Check {
	const g = "Monitor"
	var out []Check

	if !fileExists(app.ServiceDir + "/" + app.MonitorService) {
		return append(out, Check{Group: g, Name: "Service", Level: CheckWarn,
			Detail: "not installed — no watchdog and no alerts",
			Fix:    "restart the CLI (sudo parstanel); it installs the service on launch"})
	}
	if MonitorRunning() {
		return append(out, Check{Group: g, Name: "Service", Level: CheckOK,
			Detail: "running — watchdog and alerts active"})
	}
	return append(out, Check{Group: g, Name: "Service", Level: CheckFail,
		Detail: "installed but not running — dropped tunnels will NOT be restarted",
		Fix:    "systemctl restart " + app.MonitorService + " (logs: journalctl -u " + app.MonitorService + " -n 30)"})
}

func tunnelChecks() []Check {
	tunnels := List()
	if len(tunnels) == 0 {
		return []Check{{Group: "Tunnels", Name: "Configured tunnels", Level: CheckWarn,
			Detail: "none", Fix: "create one with Setup Server / Setup Client"}}
	}

	pairs := establishedPairs()

	per := make([][]Check, len(tunnels))
	var wg sync.WaitGroup
	for i, t := range tunnels {
		wg.Add(1)
		go func(i int, t Tunnel) {
			defer wg.Done()
			per[i] = tunnelChecksFor(t, pairs)
		}(i, t)
	}
	wg.Wait()

	var out []Check
	for _, c := range per {
		out = append(out, c...)
	}
	return out
}

func tunnelChecksFor(t Tunnel, pairs [][2]string) []Check {
	var out []Check
	g := "Tunnel: " + t.Name
	h := tunnelHealthWith(t, pairs)

	switch h.State {
	case "online":
		out = append(out, Check{Group: g, Name: "State", Level: CheckOK,
			Detail: fmt.Sprintf("online (%s %s)", t.Role, t.Transport)})
	case "offline":
		fix := "check the other side is running and reachable"
		if t.Role == "client" {
			fix = "verify the server address/port and that the same token is set on both sides"
		}
		out = append(out, Check{Group: g, Name: "State", Level: CheckFail,
			Detail: "service running but peer not connected", Fix: fix})
	default:
		out = append(out, Check{Group: g, Name: "State", Level: CheckWarn,
			Detail: h.Detail, Fix: "start it from Manage → Manage Tunnels"})
	}

	if IsDirectKind(t) {
		return append(out, directChecks(g, t)...)
	}

	spec, err := LoadSpec(t.Name)
	if err != nil {
		out = append(out, Check{Group: g, Name: "Config", Level: CheckFail,
			Detail: "unreadable: " + err.Error(), Fix: "restore from a backup"})
		return out
	}

	if t.Role == "server" {
		if p := addrPort(spec.BindAddr); p != "" {
			if n, _ := strconv.Atoi(p); n > 0 {
				if listening(n) || isDatagram(spec.Transport) {
					out = append(out, Check{Group: g, Name: "Tunnel port", Level: CheckOK, Detail: p + " listening"})
				} else {
					out = append(out, Check{Group: g, Name: "Tunnel port", Level: CheckFail,
						Detail: p + " not listening",
						Fix:    "the service may have failed to bind — check its log"})
				}
			}
		}
		vis := VisiblePorts(spec.Ports, spec.Token)
		if len(vis) == 0 {
			out = append(out, Check{Group: g, Name: "Forwarded ports", Level: CheckWarn,
				Detail: "none", Fix: "add ports with Manage → Manage Tunnels → Edit"})
		} else {
			out = append(out, Check{Group: g, Name: "Forwarded ports", Level: CheckOK,
				Detail: strings.Join(vis, ", ")})
		}
		if err := validatePortSpecs(vis); err != nil {
			out = append(out, Check{Group: g, Name: "Port syntax", Level: CheckFail,
				Detail: err.Error(), Fix: "fix them with Manage → Manage Tunnels → Edit"})
		}
	} else {
		host, port := addrHost(spec.RemoteAddr, ""), addrPort(spec.RemoteAddr)
		out = append(out, Check{Group: g, Name: "Server address", Level: CheckInfo, Detail: spec.RemoteAddr})
		switch {
		case host == "" || port == "":
		case isDatagram(spec.Transport):
			out = append(out, Check{Group: g, Name: "Reachability", Level: CheckInfo,
				Detail: "not testable on a UDP transport — trust the tunnel state above",
				Fix:    "if it will not connect, check that UDP " + port + " is open on the server firewall"})
		case reachable(host, port, 4*time.Second):
			out = append(out, Check{Group: g, Name: "Reachability", Level: CheckOK,
				Detail: "TCP connect to " + spec.RemoteAddr + " works"})
		default:
			out = append(out, Check{Group: g, Name: "Reachability", Level: CheckFail,
				Detail: "cannot open TCP to " + spec.RemoteAddr,
				Fix:    "check the server is up, the port matches, and the firewall allows it — or add a fallback address in Edit"})
		}
	}

	if h.State == "online" {
		out = append(out, pathChecks(g, t)...)
	}

	if t.Role == "server" && needsTLS(spec.Transport) {
		out = append(out, certCheck(g, spec.TLSCert))
	}

	switch {
	case spec.Token == "":
		out = append(out, Check{Group: g, Name: "Token", Level: CheckFail,
			Detail: "empty", Fix: "recreate the tunnel with a generated token"})
	case len(spec.Token) < 16 || spec.Token == "parstanel":
		out = append(out, Check{Group: g, Name: "Token", Level: CheckWarn,
			Detail: "weak or default", Fix: "recreate the tunnel to get a 64-char token"})
	default:
		out = append(out, Check{Group: g, Name: "Token", Level: CheckOK,
			Detail: fmt.Sprintf("%d characters", len(spec.Token))})
	}
	return out
}

func certCheck(group, path string) Check {
	if path == "" {
		return Check{Group: group, Name: "TLS certificate", Level: CheckFail,
			Detail: "not configured", Fix: "switch the transport again to auto-generate one"}
	}
	notAfter, err := CertExpiry(path)
	if err != nil {
		return Check{Group: group, Name: "TLS certificate", Level: CheckFail,
			Detail: err.Error(), Fix: "regenerate or point to a valid certificate"}
	}
	left := time.Until(notAfter)
	switch {
	case left <= 0:
		return Check{Group: group, Name: "TLS certificate", Level: CheckFail,
			Detail: "expired " + notAfter.Format("2006-01-02"),
			Fix:    "regenerate it (switch the transport again) or renew your own"}
	case left < 21*24*time.Hour:
		return Check{Group: group, Name: "TLS certificate", Level: CheckWarn,
			Detail: fmt.Sprintf("expires in %d days", int(left.Hours()/24)),
			Fix:    "renew it soon"}
	default:
		return Check{Group: group, Name: "TLS certificate", Level: CheckOK,
			Detail: "valid until " + notAfter.Format("2006-01-02")}
	}
}

func sysctlValue(key string) string {
	out, err := exec.Command("sysctl", "-n", key).Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(strings.ReplaceAll(string(out), "\t", " "))
}

func nofileForTunnels() (int, string) {
	for _, t := range List() {
		service := app.ServiceName(t.Name)
		if !IsActive(service) {
			continue
		}
		pid := mainPID(service)
		if pid <= 0 {
			continue
		}
		if v := procNofile(pid); v > 0 {
			return v, "on " + t.Name
		}
	}
	if v := unitNofile(); v > 0 {
		return v, "for a tunnel service"
	}
	return 0, ""
}

func mainPID(service string) int {
	out, err := exec.Command("systemctl", "show", "-p", "MainPID", "--value", service).Output()
	if err != nil {
		return 0
	}
	pid, _ := strconv.Atoi(strings.TrimSpace(string(out)))
	return pid
}

func procNofile(pid int) int {
	b, err := os.ReadFile(fmt.Sprintf("/proc/%d/limits", pid))
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(b), "\n") {
		if !strings.HasPrefix(line, "Max open files") {
			continue
		}
		f := strings.Fields(strings.TrimPrefix(line, "Max open files"))
		if len(f) == 0 {
			return 0
		}
		if f[0] == "unlimited" {
			return math.MaxInt32
		}
		n, _ := strconv.Atoi(f[0])
		return n
	}
	return 0
}

func unitNofile() int {
	for _, t := range List() {
		out, err := exec.Command("systemctl", "show", "-p", "LimitNOFILESoft",
			"--value", app.ServiceName(t.Name)).Output()
		if err != nil {
			continue
		}
		if n, _ := strconv.Atoi(strings.TrimSpace(string(out))); n > 0 {
			return n
		}
	}
	return 0
}

func listening(port int) bool {
	ln, err := net.Listen("tcp", fmt.Sprintf(":%d", port))
	if err != nil {
		return true
	}
	ln.Close()
	return false
}

func reachable(host, port string, timeout time.Duration) bool {
	conn, err := net.DialTimeout("tcp", net.JoinHostPort(host, port), timeout)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

func humanSize(n int) string {
	switch {
	case n >= 1<<20:
		return fmt.Sprintf("%d MB", n>>20)
	case n >= 1<<10:
		return fmt.Sprintf("%d KB", n>>10)
	default:
		return fmt.Sprintf("%d B", n)
	}
}

func Locations() []Location {
	out := []Location{
		{Label: "Binary", Path: app.BinPath},
		{Label: "Install folder", Path: app.InstallDir},
		{Label: "Backups", Path: app.BackupDir},
		{Label: "Snapshots", Path: snapshotRoot()},
		{Label: "Config folder", Path: app.ConfigDir},
		{Label: "TLS certificates", Path: app.ConfigDir + "/certs"},
		{Label: "Monitor service", Path: app.ServiceDir + "/" + app.MonitorService},
	}
	for i := range out {
		out[i].Exists = fileExists(out[i].Path)
	}
	for _, t := range List() {
		out = append(out,
			Location{Label: "Tunnel config (" + t.Name + ")", Path: app.ConfigPath(t.Name),
				Exists: fileExists(app.ConfigPath(t.Name))},
			Location{Label: "Tunnel service (" + t.Name + ")", Path: app.ServiceDir + "/" + t.Service,
				Exists: fileExists(app.ServiceDir + "/" + t.Service)},
		)
	}
	return out
}

func directChecks(g string, t Tunnel) []Check {
	var out []Check

	cfg, err := LoadTunnelConfig(t.Name)
	if err != nil {
		return append(out, Check{Group: g, Name: "Config", Level: CheckFail,
			Detail: "unreadable: " + err.Error(), Fix: "restore from a backup"})
	}

	if cfg.L3.Enabled() {
		l := cfg.L3
		out = append(out, Check{Group: g, Name: "Config", Level: CheckOK,
			Detail: "layer-3 over " + orDefault(l.Carrier, "udp") + ", " + l3EncapLabel(l)})

		iface := orDefault(l.Iface, "bp0")
		if ifaceExists(iface) {
			out = append(out, Check{Group: g, Name: "Interface", Level: CheckOK,
				Detail: iface + "  " + l.LocalIP + " -> " + l.PeerIP + ", mtu " + strconv.Itoa(l.MTU)})
		} else {
			out = append(out, Check{Group: g, Name: "Interface", Level: CheckFail,
				Detail: iface + " does not exist",
				Fix:    "a layer-3 tunnel needs root and the tun module — check its log"})
		}

		if strings.EqualFold(strings.TrimSpace(l.Carrier), "spoof") {
			out = append(out, rpFilterCheck(g, l))
		}

		if len(l.Ports) > 0 {
			out = append(out, Check{Group: g, Name: "Forwarded ports", Level: CheckOK,
				Detail: strings.Join(l.Ports, ", ")})
			if err := validatePortSpecs(l.Ports); err != nil {
				out = append(out, Check{Group: g, Name: "Port syntax", Level: CheckFail,
					Detail: err.Error(), Fix: "fix them with Manage → Manage Tunnels → Edit"})
			}
		}
		return out
	}

	d := cfg.Direct
	out = append(out, Check{Group: g, Name: "Config", Level: CheckOK,
		Detail: "direct tunnel over " + orDefault(d.Transport, "tcp")})

	if HoldsPorts(t) {
		if len(d.Ports) == 0 {
			out = append(out, Check{Group: g, Name: "Forwarded ports", Level: CheckWarn,
				Detail: "none", Fix: "add ports with Manage → Manage Tunnels → Edit"})
		} else {
			out = append(out, Check{Group: g, Name: "Forwarded ports", Level: CheckOK,
				Detail: strings.Join(d.Ports, ", ")})
			if err := validatePortSpecs(d.Ports); err != nil {
				out = append(out, Check{Group: g, Name: "Port syntax", Level: CheckFail,
					Detail: err.Error(), Fix: "fix them with Manage → Manage Tunnels → Edit"})
			}
		}
		out = append(out, Check{Group: g, Name: "Kharej server", Level: CheckInfo, Detail: d.Addr})
		return out
	}

	if p := addrPort(d.Addr); p != "" {
		if n, _ := strconv.Atoi(p); n > 0 {
			if listening(n) {
				out = append(out, Check{Group: g, Name: "Tunnel port", Level: CheckOK,
					Detail: p + " listening"})
			} else {
				out = append(out, Check{Group: g, Name: "Tunnel port", Level: CheckFail,
					Detail: p + " not listening",
					Fix:    "the service may have failed to bind — check its log"})
			}
		}
	}
	out = append(out, Check{Group: g, Name: "Forwarded ports", Level: CheckInfo,
		Detail: "set on the Iran server — this side needs none"})
	return out
}

func ifaceExists(name string) bool {
	_, err := net.InterfaceByName(name)
	return err == nil
}

func rpFilterCheck(g string, l config.L3Config) Check {
	peer := l.SpoofPeerIP
	if peer == "" && !strings.EqualFold(strings.TrimSpace(l.Mode), "listen") {
		if host, _, err := net.SplitHostPort(l.Addr); err == nil {
			peer = host
		}
	}
	iface := l.SpoofInterface
	if iface == "" {
		iface = network.InterfaceTowardPeer(peer)
	}
	v, key := network.EffectiveRPFilter(iface)
	switch v {
	case 1:
		fix := "sysctl -w net.ipv4.conf.all.rp_filter=2"
		if iface != "" {
			fix += " ; sysctl -w net.ipv4.conf." + iface + ".rp_filter=2"
		}
		return Check{Group: g, Name: "Reverse-path filter", Level: CheckFail,
			Detail: key + "=1 — the kernel drops forged-source packets before the tunnel sees them",
			Fix:    fix}
	case 0, 2:
		return Check{Group: g, Name: "Reverse-path filter", Level: CheckOK,
			Detail: "relaxed (forged sources pass)"}
	default:
		return Check{Group: g, Name: "Reverse-path filter", Level: CheckInfo,
			Detail: "could not read rp_filter; ensure it is 0 or 2 on the receiving host"}
	}
}