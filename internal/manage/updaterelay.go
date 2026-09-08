package manage

import (
	"fmt"
	"net/http"
	"sort"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/socks"
)

type RelayOption struct {
	Name  string
	Ready bool
}

func RelayOptions() []RelayOption {
	var out []RelayOption
	health := AllHealth()
	for name, h := range health {
		t, ok := Find(name)
		if !ok || t.Role != "server" || h.State != "online" {
			continue
		}
		out = append(out, RelayOption{Name: name, Ready: hasSocksPort(name)})
	}
	return orderRelayOptions(out)
}

func orderRelayOptions(in []RelayOption) []RelayOption {
	sort.SliceStable(in, func(i, j int) bool {
		if in[i].Ready != in[j].Ready {
			return in[i].Ready
		}
		return in[i].Name < in[j].Name
	})
	return in
}

func hasSocksPort(name string) bool {
	spec, err := loadServerSpec(name)
	if err != nil {
		return false
	}
	return relayExposedPort(spec.Ports, spec.Token) != ""
}

func RelayClientVia(name string, timeout time.Duration) (*http.Client, error) {
	spec, err := loadServerSpec(name)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", name, err)
	}
	port, err := EnsureSocksPort(name)
	if err != nil {
		return nil, fmt.Errorf("could not prepare %s to relay: %w", name, err)
	}
	return socks.HTTPClient(fmt.Sprintf("127.0.0.1:%d", port), "parstanel", spec.Token, timeout), nil
}