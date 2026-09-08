package manage

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"

	"github.com/hasan714222-debug/ParsTanel/internal/tui"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"
)

const rpFilterSysctlFile = "/etc/sysctl.d/99-parstanel-spoof.conf"

func OfferRelaxRPFilter(iface, peerReal string) {
	if runtime.GOOS != "linux" {
		return
	}
	if iface == "" {
		iface = network.InterfaceTowardPeer(peerReal)
	}
	v, key := network.EffectiveRPFilter(iface)
	if v != 1 {
		return
	}

	fmt.Println()
	tui.Warn("Reverse-path filtering is strict on this host (" + key + "=1).")
	tui.Warn("The kernel will DROP the forged-source packets before the tunnel")
	tui.Warn("sees them, so the tunnel will come up and carry nothing.")
	fmt.Println()
	tui.Info("Relaxing it to 2 (loose) lets the forged sources through while still")
	tui.Info("dropping packets from an address reachable nowhere at all.")
	if !tui.Confirm("Relax reverse-path filtering now", true) {
		tui.Info("Left unchanged. Set it yourself before relying on the tunnel:")
		tui.Info("  sysctl -w net.ipv4.conf.all.rp_filter=2")
		if iface != "" {
			tui.Info("  sysctl -w net.ipv4.conf." + iface + ".rp_filter=2")
		}
		return
	}

	keys := []string{"net.ipv4.conf.all.rp_filter"}
	if iface != "" {
		keys = append(keys, "net.ipv4.conf."+iface+".rp_filter")
	}
	if err := relaxRPFilter(keys); err != nil {
		tui.Error("Could not change it: " + err.Error())
		tui.Warn("Set it by hand: sysctl -w net.ipv4.conf.all.rp_filter=2")
		return
	}
	tui.Success("Reverse-path filtering relaxed (and saved to " + rpFilterSysctlFile + ").")
	tui.Info("If a forged source still does not pass the tester, set these to 0 instead.")
}

func relaxRPFilter(keys []string) error {
	var b strings.Builder
	b.WriteString("# Managed by parstanel — reverse-path filtering for the spoof carrier\n")
	for _, k := range keys {
		fmt.Fprintf(&b, "%s = 2\n", k)
	}
	_ = os.WriteFile(rpFilterSysctlFile, []byte(b.String()), 0644)

	applied := 0
	for _, k := range keys {
		if err := exec.Command("sysctl", "-w", k+"=2").Run(); err == nil {
			applied++
		}
	}
	if applied == 0 {
		return fmt.Errorf("no rp_filter key could be set (is this host running as root?)")
	}
	return nil
}