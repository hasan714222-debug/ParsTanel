package manage

import (
	"fmt"
	"os"
	"strings"

	"github.com/BurntSushi/toml"
	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/tui"
)

func editDirectMenu(t Tunnel) {
	for {
		cfg, err := LoadTunnelConfig(t.Name)
		if err != nil {
			tui.Error("Cannot read the tunnel config: " + err.Error())
			tui.PressEnter()
			return
		}

		tui.Clear()
		tui.Title("Edit — " + t.Name)
		fmt.Println()

		if cfg.Direct.Enabled() {
			if !editDirectPorts(t, cfg) {
				return
			}
			continue
		}
		if !editL3Ports(t, cfg) {
			return
		}
	}
}

func editDirectPorts(t Tunnel, cfg config.Config) bool {
	d := cfg.Direct
	iran := d.ResolvedRole() == "edge"

	tui.Info("Kind         : direct tunnel, forwarded ports")
	tui.Info("This machine : " + directRole(d.ResolvedRole()))
	tui.Info("Transport    : " + orDefault(d.Transport, "tcp"))
	if iran {
		tui.Info("Dials        : " + d.Addr)
		tui.Info("Ports        : " + strings.Join(d.Ports, ", "))
		tui.Info("UDP          : " + onOff(d.AcceptUDP))
		tui.Info("Tuning       : " + presetLabel(d.Preset) + fmt.Sprintf(", %d session(s)", max(d.Sessions, 1)))
		tui.Info("Limits       : " + limitsLabel(d.MaxConnections, d.BandwidthMbps))
	} else {
		tui.Info("Listens on   : " + d.Addr)
		fmt.Println()
		tui.Warn("The kharej side holds no port list — what is forwarded is set on")
		tui.Warn("the Iran server, so there is nothing to change here.")
	}
	fmt.Println()

	if !iran {
		tui.PressEnter()
		return false
	}

	switch tui.ChooseOpt("Change what?", []tui.Option{
		{Title: "Forwarded ports", Desc: "the ports exposed on this machine"},
		{Title: "UDP forwarding", Desc: "carry UDP as well as TCP — currently " + onOff(d.AcceptUDP)},
		{Title: "Limits", Desc: "connections and bandwidth — currently " + limitsLabel(d.MaxConnections, d.BandwidthMbps)},
		{Title: "Performance tuning", Desc: "currently " + presetLabel(d.Preset)},
		{Title: "TCP segment cap", Desc: "for a path that stalls on full-sized packets — currently " + directMSSLabel(d.MSS)},
		{Title: "Show the token", Desc: "reveal it, to copy to the other machine"},
	}) {
	case 0:
		raw := tui.Prompt("Ports (comma separated, e.g. 443,8080=80): ")
		ports := parsePorts(raw)
		if len(ports) == 0 {
			tui.Error("No valid ports entered.")
			tui.PressEnter()
			return true
		}
		if err := validatePortSpecs(ports); err != nil {
			tui.Error(err.Error())
			tui.PressEnter()
			return true
		}
		d.Ports = ports
		showForwardTargets(ports, d.AcceptUDP)
		saveDirect(t, d)
	case 1:
		d.AcceptUDP = tui.Confirm("Carry UDP as well as TCP", d.AcceptUDP)
		saveDirect(t, d)
	case 2:
		d.MaxConnections = tui.PromptInt("Maximum simultaneous connections (0 = unlimited)", d.MaxConnections)
		d.BandwidthMbps = tui.PromptInt("Maximum bandwidth in Mbit/s (0 = unlimited)", d.BandwidthMbps)
		saveDirect(t, d)
	case 3:
		p := chooseDirectPreset()
		d.Preset = p.Name
		d.MaxFrameSize = p.MuxFrameSize
		d.MaxReceiveBuffer = p.MuxReceiveBuffer
		d.MaxStreamBuffer = p.MuxStreamBuffer
		if p.Sessions > d.Sessions {
			d.Sessions = p.Sessions
		}
		saveDirect(t, d)
	case 4:
		fmt.Println()
		tui.Info("Some paths carry less than a full-sized packet and drop the")
		tui.Info("oversized ones without an ICMP reply. Nothing on either machine")
		tui.Info("learns: the handshake and the keepalives are small enough to")
		tui.Info("arrive, so the tunnel comes up and stays up while every real")
		tui.Info("transfer stalls on the first full segment.")
		fmt.Println()
		tui.Warn("Set this on BOTH machines — each end clamps only what it sends.")
		tui.Info("1360 is a safe first try. 0 hands the decision back to the kernel.")
		mss := tui.PromptInt("TCP segment cap in bytes (0 = let the kernel decide)", d.MSS)
		if mss != 0 && (mss < minMSS || mss > maxMSS) {
			tui.Error(fmt.Sprintf("A segment cap must be between %d and %d bytes, or 0.", minMSS, maxMSS))
			tui.PressEnter()
			return true
		}
		d.MSS = mss
		saveDirect(t, d)
	case 5:
		fmt.Println()
		tui.Info("Token (must match the other machine exactly):")
		fmt.Println("  " + tui.Color(tui.Bold+tui.White, d.Token))
		tui.PressEnter()
	default:
		return false
	}
	return true
}

func directMSSLabel(mss int) string {
	if mss <= 0 {
		return "off (the kernel decides)"
	}
	return fmt.Sprintf("%d bytes", mss)
}

func editL3Ports(t Tunnel, cfg config.Config) bool {
	l := cfg.L3
	iran := !strings.EqualFold(strings.TrimSpace(l.Mode), "listen")

	tui.Info("Kind         : full IP tunnel (layer 3)")
	tui.Info("This machine : " + l3Role(l.Mode))
	tui.Info("Carrier      : " + orDefault(l.Carrier, "udp"))
	tui.Info("Wrapping     : " + l3EncapLabel(l))
	tui.Info("Address      : " + l.Addr)
	tui.Info("Interface    : " + orDefault(l.Iface, "bp0") + "  " + l.LocalIP + " ↔ " + l.PeerIP)
	tui.Info("MTU          : " + fmt.Sprint(l.MTU))
	tui.Info("Tuning       : " + presetLabel(l.Preset) + ", " + orDefault(l.Qdisc, "fq_codel"))
	if len(l.Ports) > 0 {
		tui.Info("Ports        : " + strings.Join(l.Ports, ", "))
		tui.Info("UDP          : " + onOff(l.AcceptUDP))
	}
	fmt.Println()

	options := []tui.Option{
		{Title: "MTU", Desc: "lower it if large transfers stall — currently " + fmt.Sprint(l.MTU)},
		{Title: "TCP segment cap", Desc: "currently " + mssClampLabel(l.MSSClamp, l.MTU)},
		{Title: "Show the token", Desc: "reveal it, to copy to the other machine"},
	}
	if strings.EqualFold(strings.TrimSpace(l.Carrier), "spoof") {
		options = append(options, tui.Option{
			Title: "IP Spoofing",
			Desc:  "the forged source, the packet profile, Stealth — currently " + spoofCarrierSummary(l.SpoofConfig),
		})
	}
	if iran {
		options = append([]tui.Option{
			{Title: "Forwarded ports", Desc: "optional ports carried over the tunnel"},
			{Title: "UDP forwarding", Desc: "carry UDP as well as TCP — currently " + onOff(l.AcceptUDP)},
		}, options...)
	}

	choice, ok := l3EditAction(tui.ChooseOpt("Change what?", options), iran)
	if !ok {
		return false
	}

	switch choice {
	case 0:
		raw := tui.Prompt("Ports (comma separated, blank to remove them all): ")
		if strings.TrimSpace(raw) == "" {
			l.Ports = nil
		} else {
			ports := parsePorts(raw)
			if err := validatePortSpecs(ports); err != nil {
				tui.Error(err.Error())
				tui.PressEnter()
				return true
			}
			l.Ports = ports
		}
		saveL3(t, l)
	case 1:
		l.AcceptUDP = tui.Confirm("Carry UDP as well as TCP", l.AcceptUDP)
		saveL3(t, l)
	case 2:
		fmt.Println()
		tui.Warn("A tunnel whose packets are slightly too big does not fail loudly:")
		tui.Warn("small things work and downloads stall. Lower it if that happens.")
		l.MTU = tui.PromptInt("Tunnel MTU", l.MTU)
		saveL3(t, l)
	case 3:
		fmt.Println()
		tui.Info("This caps the segment size of TCP crossing the tunnel, so both")
		tui.Info("ends agree on something that fits before they send anything.")
		tui.Info("0 derives it from the MTU, which is almost always right.")
		l.MSSClamp = tui.PromptInt("TCP segment cap (0 = from the MTU, -1 = off)", l.MSSClamp)
		saveL3(t, l)
	case 4:
		fmt.Println()
		tui.Info("Token (must match the other machine exactly):")
		fmt.Println("  " + tui.Color(tui.Bold+tui.White, l.Token))
		tui.PressEnter()
	case 5:
		if editL3Spoof(t, l) {
			return true
		}
	default:
		return false
	}
	return true
}

const l3EditActionShift = 2

func l3EditAction(chosen int, iran bool) (action int, ok bool) {
	if chosen < 0 {
		return 0, false
	}
	if iran {
		return chosen, true
	}
	return chosen + l3EditActionShift, true
}

func mssClampLabel(clamp, mtu int) string {
	switch {
	case clamp == mssClampOffLabel:
		return "off"
	case clamp > 0:
		return fmt.Sprint(clamp) + " bytes"
	default:
		return fmt.Sprintf("automatic (%d bytes, from the MTU)", mtu-40)
	}
}

const mssClampOffLabel = -1

func saveDirect(t Tunnel, d config.DirectConfig) {
	side := sideIran
	if d.ResolvedRole() == "origin" {
		side = sideKharej
	}
	spec := directSpec{
		Name: t.Name, Side: side,
		Transport: orDefault(d.Transport, "tcp"),
		Addr:      d.Addr, Token: d.Token,
		Ports: d.Ports, AcceptUDP: d.AcceptUDP,
		MaxConnections: d.MaxConnections, BandwidthMbps: d.BandwidthMbps,
		Sessions:     d.Sessions,
		Preset:       d.Preset,
		MuxFrameSize: d.MaxFrameSize, MuxReceiveBuffer: d.MaxReceiveBuffer,
		MuxStreamBuffer: d.MaxStreamBuffer, Keepalive: d.Keepalive,
		Nodelay:    d.Nodelay,
		ServerName: d.ServerName,
		ACMEDomain: d.ACMEDomain, ACMEEmail: d.ACMEEmail,
		TLSCertFile: d.TLSCertFile, TLSKeyFile: d.TLSKeyFile,
		MuxVersion:  d.MuxVersion,
		DialTimeout: d.DialTimeout, RetryInterval: d.RetryInterval,
		MSS: d.MSS,
	}
	applyEdit(t, spec.render())
}

func saveL3(t Tunnel, l config.L3Config) {
	side := sideIran
	if strings.EqualFold(strings.TrimSpace(l.Mode), "listen") {
		side = sideKharej
	}
	spec := l3Spec{
		Name: t.Name, Side: side,
		Carrier: orDefault(l.Carrier, "udp"),
		Encap:   "gre", GREKey: l.GREKey,
		Addr: l.Addr, Token: l.Token,
		Iface:   orDefault(l.Iface, "bp0"),
		LocalIP: l.LocalIP, PeerIP: l.PeerIP, MTU: l.MTU,
		SockBuf: l.SockBuf, MSSClamp: l.MSSClamp, AutoMTU: l.AutoMTU,
		FECData: l.FECData, FECParity: l.FECParity,
		Paths:  l.Paths,
		Preset: l.Preset, TxQueueLen: l.TxQueueLen, Qdisc: l.Qdisc,
		Ports: l.Ports, AcceptUDP: l.AcceptUDP,
		MaxConnections: l.MaxConnections, BandwidthMbps: l.BandwidthMbps,
		Spoof: l.SpoofConfig,
		Pck:   l.PckConfig,
	}
	applyEdit(t, spec.render())
}

func applyEdit(t Tunnel, body string) {
	var check config.Config
	if _, err := toml.Decode(body, &check); err != nil {
		tui.Error("The edit produced a config that does not parse: " + err.Error())
		tui.PressEnter()
		return
	}
	if err := os.WriteFile(app.ConfigPath(t.Name), []byte(body), 0644); err != nil {
		tui.Error("Cannot write the config: " + err.Error())
		tui.PressEnter()
		return
	}
	if err := RestartService(t.Service); err != nil {
		tui.Error("Saved, but the restart failed: " + err.Error())
		tui.Warn("Check the log with:  journalctl -u " + t.Service + " -n 50")
		tui.PressEnter()
		return
	}
	tui.Success("Saved and restarted.")
	tui.PressEnter()
}

func spoofCarrierSummary(sc config.SpoofConfig) string {
	profile := orDefault(sc.SpoofProfile, "udp")
	if sc.SpoofUplink != "" || sc.SpoofDownlink != "" {
		profile = orDefault(sc.SpoofUplink, profile) + "/" + orDefault(sc.SpoofDownlink, profile)
	}
	source := "unforged"
	switch {
	case len(sc.SpoofSrcPool) > 1:
		source = fmt.Sprintf("%d forged sources", len(sc.SpoofSrcPool))
	case sc.SpoofSrcIP != "":
		source = sc.SpoofSrcIP
	}
	stealth := "Stealth off"
	if spoofStealthOn(sc) {
		stealth = "Stealth on"
	}
	return profile + ", " + source + ", " + stealth
}

func editL3Spoof(t Tunnel, l config.L3Config) bool {
	onIran := !strings.EqualFold(strings.TrimSpace(l.Mode), "listen")
	there := "kharej"
	if !onIran {
		there = "Iran"
	}

	stealth := "Turn Stealth on"
	if spoofStealthOn(l.SpoofConfig) {
		stealth = "Turn Stealth off"
	}

	switch tui.ChooseOpt("IP Spoofing — change what?", []tui.Option{
		{Title: stealth, Desc: "padding and header cosmetics — the " + there + " end must be set the same way"},
		{Title: "Run the setup again", Desc: "the profile, the forged source, the interface — every question, from the top"},
	}) {
	case 0:
		if spoofStealthOn(l.SpoofConfig) {
			clearSpoofStealth(&l.SpoofConfig)
		} else {
			applySpoofStealth(&l.SpoofConfig)
		}
		fmt.Println()
		tui.Warn("Set the " + there + " end the same way, or the tunnel will come up and")
		tui.Warn("carry nothing: padding and the TLS header change what goes on the wire.")
		tui.PressEnter()
		saveL3(t, l)
		return true
	case 1:
		askSpoofCarrier(&l.SpoofConfig, onIran)
		tui.PressEnter()
		saveL3(t, l)
		return true
	}
	return false
}
