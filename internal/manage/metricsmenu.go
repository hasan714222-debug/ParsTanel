package manage

import (
	"fmt"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/metrics"
	"github.com/hasan714222-debug/ParsTanel/internal/sysstat"
	"github.com/hasan714222-debug/ParsTanel/internal/tui"
)

func TunnelMetrics() {
	tui.Clear()
	tui.Title("Tunnel Metrics")
	tui.Warn("Measured from the traffic each tunnel actually carried.")
	fmt.Println()

	tunnels := List()
	if len(tunnels) == 0 {
		tui.Warn("No tunnels configured yet.")
		tui.PressEnter()
		return
	}

	shown := 0
	for _, t := range tunnels {
		snap, err := metrics.Read(app.ConfigDir, t.Name)
		if err != nil {
			tui.Info(tui.Color(tui.Bold+tui.White, t.Name))
			if IsActive(t.Service) {
				tui.Warn("  no readings yet — a tunnel writes its first one within 30 seconds of starting")
			} else {
				tui.Warn("  not running")
			}
			fmt.Println()
			continue
		}
		shown++
		printSnapshot(t, snap)
	}

	if shown == 0 {
		tui.Warn("Nothing has been recorded yet. Start a tunnel and come back in a minute.")
	}
	tui.PressEnter()
}

func printSnapshot(t Tunnel, s metrics.Snapshot) {
	tui.Info(tui.Color(tui.Bold+tui.White, t.Name) +
		tui.Color(tui.Gray, fmt.Sprintf("  %s / %s", s.Role, transportLabel(s.Transport))))

	age := time.Since(s.Taken).Round(time.Second)
	tui.Warn(fmt.Sprintf("  recorded %s ago, tunnel up for %s", age, s.Uptime))
	tui.Info(fmt.Sprintf("  Traffic       : %s in, %s out",
		sysstat.HumanBytes(s.BytesIn), sysstat.HumanBytes(s.BytesOut)))

	if s.KCP == nil {
		fmt.Println()
		return
	}

	k := s.KCP
	tui.Info(fmt.Sprintf("  Packets       : %d in, %d out", k.PacketsIn, k.PacketsOut))

	lossLine := fmt.Sprintf("  Link quality  : %.2f%% of packets needed repair", k.LossPercent())
	switch {
	case k.LossPercent() >= 5:
		tui.Error(lossLine)
	case k.LossPercent() >= 1:
		tui.Warn(lossLine)
	default:
		tui.Info(lossLine)
	}
	tui.Warn(fmt.Sprintf("      resent %d, lost %d, duplicated %d",
		k.Retransmitted, k.Lost, k.Duplicated))

	if k.FECRecovered > 0 {
		tui.Success(fmt.Sprintf("  Error correct.: %d packets rebuilt from parity — repaired without a retransmit",
			k.FECRecovered))
		if k.FECErrors > 0 {
			tui.Warn(fmt.Sprintf("      %d parity groups were too damaged to rebuild", k.FECErrors))
		}
	} else if k.PacketsIn > 0 {
		tui.Info("  Error correct.: nothing needed rebuilding — this link is clean")
		tui.Warn("      on a link this good, TCP Mux would be faster and lighter on CPU")
	}
	fmt.Println()
}