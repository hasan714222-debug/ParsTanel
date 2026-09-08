package manage

import (
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/BurntSushi/toml"
	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

type Tunnel struct {
	Name      string
	Role      string
	Transport string
	Addr      string
	Ports     []string
	Service   string
}

func List() []Tunnel {
	var tunnels []Tunnel
	matches, _ := filepath.Glob(app.ConfigDir + "/*.toml")
	for _, path := range matches {
		var cfg config.Config
		if _, err := toml.DecodeFile(path, &cfg); err != nil {
			continue
		}
		name := strings.TrimSuffix(filepath.Base(path), ".toml")
		t := Tunnel{Name: name, Service: app.ServiceName(name)}
		switch {
		case cfg.Server.BindAddr != "":
			t.Role = "server"
			t.Transport = string(cfg.Server.Transport)
			t.Addr = cfg.Server.BindAddr
			t.Ports = cfg.Server.Ports
		case cfg.Client.RemoteAddr != "":
			t.Role = "client"
			t.Transport = string(cfg.Client.Transport)
			t.Addr = cfg.Client.RemoteAddr
		case cfg.Direct.Enabled():
			t.Role = directRole(cfg.Direct.ResolvedRole())
			t.Transport = "direct/" + orDefault(cfg.Direct.Transport, "tcp")
			t.Addr = cfg.Direct.Addr
			t.Ports = cfg.Direct.Ports
		case cfg.L3.Enabled():
			t.Role = l3Role(cfg.L3.Mode)
			t.Transport = "l3/" + orDefault(cfg.L3.Carrier, "udp")
			t.Addr = cfg.L3.Addr
			t.Ports = cfg.L3.Ports
		default:
			continue
		}
		tunnels = append(tunnels, t)
	}
	sort.Slice(tunnels, func(i, j int) bool { return tunnels[i].Name < tunnels[j].Name })
	return tunnels
}

func LoadTunnelConfig(name string) (config.Config, error) {
	var cfg config.Config
	_, err := toml.DecodeFile(app.ConfigPath(name), &cfg)
	return cfg, err
}

func Delete(name string) error {
	service := app.ServiceName(name)
	if IsActive(service) || IsEnabled(service) {
		_ = DisableService(service)
	}
	removeUnit(name)
	os.Remove(app.ConfigPath(name))
	deleteTunnelMeta(name)
	return DaemonReload()
}

func RestartAll() (ok, failed int) {
	for _, t := range List() {
		if err := RestartService(t.Service); err != nil {
			failed++
		} else {
			ok++
		}
	}
	return ok, failed
}

func Find(name string) (Tunnel, bool) {
	for _, t := range List() {
		if t.Name == name {
			return t, true
		}
	}
	return Tunnel{}, false
}