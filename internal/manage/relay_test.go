package manage

import (
	"fmt"
	"testing"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

func TestLegacySocksInUse(t *testing.T) {
	legacyMapping := fmt.Sprintf("9000=127.0.0.1:%d", app.SocksInternalPort)

	cases := []struct {
		name    string
		tunnels []Tunnel
		want    bool
	}{
		{"no tunnels", nil, false},
		{"a tunnel with no ports", []Tunnel{{Name: "a"}}, false},
		{
			"only derived-port mappings",
			[]Tunnel{{Name: "a", Ports: []string{"9000=127.0.0.1:34567", "22=127.0.0.1:22"}}},
			false,
		},
		{
			"a legacy 1080 mapping",
			[]Tunnel{{Name: "a", Ports: []string{legacyMapping}}},
			true,
		},
		{
			"legacy mapping among others",
			[]Tunnel{
				{Name: "a", Ports: []string{"80=127.0.0.1:8080"}},
				{Name: "b", Ports: []string{"443=127.0.0.1:443", legacyMapping}},
			},
			true,
		},
		{
			"whitespace around the mapping",
			[]Tunnel{{Name: "a", Ports: []string{"  " + legacyMapping + "  "}}},
			true,
		},
		{
			"1080 on the wrong side of the mapping",
			[]Tunnel{{Name: "a", Ports: []string{"1080=127.0.0.1:9000"}}},
			false,
		},
		{
			"1080 on another host",
			[]Tunnel{{Name: "a", Ports: []string{"9000=10.0.0.5:1080"}}},
			false,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := LegacySocksInUse(tc.tunnels); got != tc.want {
				t.Fatalf("LegacySocksInUse = %v, want %v", got, tc.want)
			}
		})
	}
}