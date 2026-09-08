package cmd

import (
	"context"
	"net"
	"os"
	"reflect"
	"time"

	"github.com/hasan714222-debug/ParsTanel/config"
)

// configPollInterval is how often the file is checked.
const configPollInterval = 2 * time.Second

// portSettleTimeout bounds how long to wait for the stopped tunnel's ports to
// come free before starting the new one anyway.
const portSettleTimeout = 5 * time.Second

// fingerprint is a cheap identity for the file's current contents.
type fingerprint struct {
	size    int64
	modTime time.Time
}

func fileFingerprint(path string) (fingerprint, error) {
	fi, err := os.Stat(path)
	if err != nil {
		return fingerprint{}, err
	}
	return fingerprint{size: fi.Size(), modTime: fi.ModTime()}, nil
}

// awaitConfigChange blocks until the file at path holds a configuration that
// differs from current, and returns it. It returns nil when ctx ends.
func awaitConfigChange(ctx context.Context, path string, current *config.Config) *config.Config {
	last, err := fileFingerprint(path)
	if err != nil {
		logger.Debugf("cannot stat the configuration file: %v", err)
	}
	var lastComplaint fingerprint

	ticker := time.NewTicker(configPollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}

		fp, err := fileFingerprint(path)
		if err != nil || fp == last {
			continue
		}
		last = fp

		next, err := loadConfig(path)
		if err != nil {
			if fp != lastComplaint {
				lastComplaint = fp
				logger.Errorf("the configuration file changed but does not parse, so the tunnel keeps running the previous one: %v", err)
			}
			continue
		}
		applyDefaults(next)

		if reflect.DeepEqual(current, next) {
			logger.Debug("the configuration file changed but means the same thing; leaving the tunnel alone")
			continue
		}
		return next
	}
}

// listenerBinding is an address together with the protocol whose socket has to
// come free before the address counts as available.
type listenerBinding struct {
	network string
	address string
}

// waitForPorts waits until every binding can be taken, so the tunnel being
// started is not racing the one that just stopped for its own ports.
func waitForPorts(ctx context.Context, bindings []listenerBinding) {
	for _, binding := range bindings {
		if binding.address == "" || (binding.network != "tcp" && binding.network != "udp") {
			continue
		}
		deadline := time.Now().Add(portSettleTimeout)
		for time.Now().Before(deadline) {
			if bindingIsFree(binding) {
				break
			}
			select {
			case <-ctx.Done():
				return
			case <-time.After(100 * time.Millisecond):
			}
		}
	}
}

// bindingIsFree reports whether the address can be taken right now.
func bindingIsFree(binding listenerBinding) bool {
	switch binding.network {
	case "tcp":
		ln, err := net.Listen("tcp", binding.address)
		if err != nil {
			return false
		}
		ln.Close()
		return true
	case "udp":
		pc, err := net.ListenPacket("udp", binding.address)
		if err != nil {
			return false
		}
		pc.Close()
		return true
	default:
		return false
	}
}

// portsInUse names the addresses a run binds that can be known from the
// configuration alone.
func portsInUse(cfg *config.Config) []listenerBinding {
	var bindings []listenerBinding
	if cfg.Server.BindAddr != "" {
		if network := tunnelNetwork(cfg.Server.Transport); network != "" {
			bindings = append(bindings, listenerBinding{network: network, address: cfg.Server.BindAddr})
		}
		if cfg.Server.WebPort > 0 {
			bindings = append(bindings, listenerBinding{network: "tcp", address: net.JoinHostPort("", itoa(cfg.Server.WebPort))})
		}
		return bindings
	}
	if cfg.Client.WebPort > 0 {
		bindings = append(bindings, listenerBinding{network: "tcp", address: net.JoinHostPort("", itoa(cfg.Client.WebPort))})
	}
	return bindings
}

func tunnelNetwork(transport config.TransportType) string {
	switch transport {
	case config.UDP, config.KCP, config.QUIC:
		return "udp"
	case config.XDI, config.SPOOF, config.PCK:
		return ""
	default:
		return "tcp"
	}
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var b [8]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = byte('0' + n%10)
		n /= 10
	}
	return string(b[i:])
}
