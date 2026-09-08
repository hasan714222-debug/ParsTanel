package manage

import (
	"fmt"
	"os"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

const monitorUnit = `[Unit]
Description=ParsTanel Monitor (watchdog, Telegram bot and alerts)
After=network.target

[Service]
Type=simple
ExecStart=%s --monitor
Restart=always
RestartSec=5
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
`

func EnsureMonitorService() error {
	path := app.ServiceDir + "/" + app.MonitorService
	want := fmt.Sprintf(monitorUnit, app.BinPath)

	current, err := os.ReadFile(path)
	unchanged := err == nil && string(current) == want

	if unchanged {
		if IsActive(app.MonitorService) {
			return nil
		}
		return StartService(app.MonitorService)
	}

	if err := os.WriteFile(path, []byte(want), 0644); err != nil {
		return err
	}
	if err := DaemonReload(); err != nil {
		return err
	}
	if IsActive(app.MonitorService) {
		return RestartService(app.MonitorService)
	}
	return StartService(app.MonitorService)
}

func RestartMonitorService() error {
	if err := EnsureMonitorService(); err != nil {
		return err
	}
	return RestartService(app.MonitorService)
}

func DisableMonitorService() error {
	if IsActive(app.MonitorService) || IsEnabled(app.MonitorService) {
		DisableService(app.MonitorService)
	}
	os.Remove(app.ServiceDir + "/" + app.MonitorService)
	return DaemonReload()
}

func MonitorRunning() bool { return IsActive(app.MonitorService) }
