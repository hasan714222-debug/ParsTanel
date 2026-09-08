package manage

import (
	"fmt"
	"os"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/localproxy"
)

const proxyUnit = `[Unit]
Description=ParsTanel built-in proxy (SOCKS5/HTTP)
After=network.target

[Service]
Type=simple
ExecStart=%s --proxy
Restart=always
RestartSec=5
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
`

func EnableProxyService(cfg localproxy.Config) error {
	cfg.Enabled = true
	if cfg.Port <= 0 || cfg.Port > 65535 {
		return fmt.Errorf("choose a port between 1 and 65535")
	}
	if err := localproxy.Save(cfg); err != nil {
		return err
	}
	path := app.ServiceDir + "/" + app.ProxyService
	if err := os.WriteFile(path, fmt.Appendf(nil, proxyUnit, app.BinPath), 0644); err != nil {
		return err
	}
	if err := DaemonReload(); err != nil {
		return err
	}
	if IsActive(app.ProxyService) {
		return RestartService(app.ProxyService)
	}
	return StartService(app.ProxyService)
}

func DisableProxyService() error {
	if IsActive(app.ProxyService) || IsEnabled(app.ProxyService) {
		DisableService(app.ProxyService)
	}
	os.Remove(app.ServiceDir + "/" + app.ProxyService)
	cfg := localproxy.Load()
	cfg.Enabled = false
	_ = localproxy.Save(cfg)
	return DaemonReload()
}

func ProxyRunning() bool { return IsActive(app.ProxyService) }