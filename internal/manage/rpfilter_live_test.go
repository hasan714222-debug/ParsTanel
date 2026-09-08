//go:build linux

package manage

import (
	"os"
	"testing"

	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"
)

func TestRelaxRPFilterLive(t *testing.T) {
	if os.Getenv("BP_RPFILTER_LIVE") == "" {
		t.Skip("set BP_RPFILTER_LIVE=1 in a namespace with a writable /proc to run this")
	}
	if v, _ := network.EffectiveRPFilter(""); v != 1 {
		t.Fatalf("expected a strict rp_filter to start from, got %d", v)
	}
	if err := relaxRPFilter([]string{"net.ipv4.conf.all.rp_filter"}); err != nil {
		t.Fatalf("relaxRPFilter: %v", err)
	}
	if v, key := network.EffectiveRPFilter(""); v == 1 {
		t.Fatalf("%s is still strict after relaxing", key)
	}
	if _, err := os.Stat(rpFilterSysctlFile); err == nil {
		t.Logf("relaxation also persisted to %s", rpFilterSysctlFile)
	} else {
		t.Logf("live change applied; persistence skipped (%v) — expected off a real root fs", err)
	}
}