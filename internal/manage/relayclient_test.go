package manage

import (
	"fmt"
	"testing"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

func TestRelayFoundForTokenDerivedPort(t *testing.T) {
	const token = "a-real-looking-token-0123456789abcdef"
	peer := app.SocksPortForToken(token)
	ports := []string{"443=1.1.1.1:443", fmt.Sprintf("41234=127.0.0.1:%d", peer)}

	if got := relayExposedPort(ports, token); got != "41234" {
		t.Fatalf("relayExposedPort = %q, want \"41234\"", got)
	}
}

func TestRelayFoundForLegacyPort(t *testing.T) {
	ports := []string{fmt.Sprintf("41234=127.0.0.1:%d", app.SocksInternalPort)}
	if got := relayExposedPort(ports, "some-token"); got != "41234" {
		t.Errorf("relayExposedPort = %q, want \"41234\" for a legacy 1080 mapping", got)
	}
}

func TestRelayPortIsReadThroughABindAddress(t *testing.T) {
	const token = "another-token-0123456789abcdefghij"
	peer := app.SocksPortForToken(token)
	ports := []string{fmt.Sprintf("127.0.0.1:41234=127.0.0.1:%d", peer)}

	if got := relayExposedPort(ports, token); got != "41234" {
		t.Errorf("relayExposedPort = %q, want \"41234\"", got)
	}
}

func TestNoRelayWhenNoMappingExists(t *testing.T) {
	for _, ports := range [][]string{
		{"443=1.1.1.1:443", "8080"},
		{"443-450"},
		nil,
	} {
		if got := relayExposedPort(ports, "some-token"); got != "" {
			t.Errorf("relayExposedPort(%v) = %q, want \"\"", ports, got)
		}
	}
}

func TestEmptyTokenOnlyMatchesTheLegacyPort(t *testing.T) {
	const other = "someone-elses-token-0123456789abcd"
	ports := []string{fmt.Sprintf("41234=127.0.0.1:%d", app.SocksPortForToken(other))}

	if got := relayExposedPort(ports, ""); got != "" {
		t.Errorf("relayExposedPort = %q for an unrelated tunnel's derived port", got)
	}
}
