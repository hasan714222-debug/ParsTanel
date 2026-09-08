package manage

import (
	"strings"
	"testing"

	"github.com/BurntSushi/toml"
	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/tunnel/l3"
)

func TestFECSurvivesARenderRoundTrip(t *testing.T) {
	spec := l3Spec{
		Name: "lossy", Side: sideIran, Carrier: "udp",
		Addr: "203.0.113.9:9000", Token: "a-token-0123456789abcdefghijklmno",
		LocalIP: "10.20.0.1/30", PeerIP: "10.20.0.2",
		Ports:     []string{"443"},
		FECData:   10,
		FECParity: 3,
	}
	var got config.Config
	if _, err := toml.Decode(spec.render(), &got); err != nil {
		t.Fatalf("the rendered config does not parse: %v", err)
	}
	if got.L3.FECData != 10 || got.L3.FECParity != 3 {
		t.Errorf("fec did not survive: data=%d parity=%d", got.L3.FECData, got.L3.FECParity)
	}
}

func TestAHalfSchemeIsNotRendered(t *testing.T) {
	for _, spec := range []l3Spec{
		{Name: "a", Side: sideIran, Carrier: "udp", Addr: "203.0.113.9:9000",
			Token: "a-token-0123456789abcdefghijklmno", LocalIP: "10.20.0.1/30",
			PeerIP: "10.20.0.2", Ports: []string{"443"}, FECData: 10},
		{Name: "b", Side: sideIran, Carrier: "udp", Addr: "203.0.113.9:9000",
			Token: "a-token-0123456789abcdefghijklmno", LocalIP: "10.20.0.1/30",
			PeerIP: "10.20.0.2", Ports: []string{"443"}, FECParity: 3},
	} {
		if out := spec.render(); strings.Contains(out, "fec_") {
			t.Errorf("a half-configured scheme was written out:\n%s", out)
		}
	}
}

func TestNoFECWritesNothing(t *testing.T) {
	spec := l3Spec{
		Name: "clean", Side: sideIran, Carrier: "udp",
		Addr: "203.0.113.9:9000", Token: "a-token-0123456789abcdefghijklmno",
		LocalIP: "10.20.0.1/30", PeerIP: "10.20.0.2", Ports: []string{"443"},
	}
	if out := spec.render(); strings.Contains(out, "fec_") {
		t.Errorf("a tunnel with no error correction rendered fec keys:\n%s", out)
	}
}

func TestTheRecommendedSchemeIsValid(t *testing.T) {
	plan := defaultL3FEC()
	if !plan.Set() {
		t.Fatal("the recommended scheme is not a scheme")
	}
	if plan.Parity >= plan.Data {
		t.Fatalf("the recommended scheme sends %d spare per %d — more redundancy than payload",
			plan.Parity, plan.Data)
	}
	if err := (l3FECFrom(plan)).Validate(); err != nil {
		t.Errorf("the engine refuses the wizard's recommendation: %v", err)
	}
}

func l3FECFrom(p FECPlan) l3.FECConfig {
	return l3.FECConfig{Data: p.Data, Parity: p.Parity}
}

func TestPathsSurviveARenderRoundTrip(t *testing.T) {
	spec := l3Spec{
		Name: "shaped", Side: sideIran, Carrier: "udp",
		Addr: "203.0.113.9:9000", Token: "a-token-0123456789abcdefghijklmno",
		LocalIP: "10.20.0.1/30", PeerIP: "10.20.0.2",
		Ports: []string{"443"}, Paths: 4,
	}
	var got config.Config
	if _, err := toml.Decode(spec.render(), &got); err != nil {
		t.Fatalf("the rendered config does not parse: %v", err)
	}
	if got.L3.Paths != 4 {
		t.Errorf("paths = %d, want 4", got.L3.Paths)
	}
}

func TestASingleSocketWritesNoPathsKey(t *testing.T) {
	for _, n := range []int{0, 1} {
		spec := l3Spec{
			Name: "plain", Side: sideIran, Carrier: "udp",
			Addr: "203.0.113.9:9000", Token: "a-token-0123456789abcdefghijklmno",
			LocalIP: "10.20.0.1/30", PeerIP: "10.20.0.2",
			Ports: []string{"443"}, Paths: n,
		}
		if out := spec.render(); strings.Contains(out, "paths") {
			t.Errorf("paths=%d rendered a key:\n%s", n, out)
		}
	}
}