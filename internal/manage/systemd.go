package manage

import (
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

func systemctl(args ...string) (string, error) {
	out, err := exec.Command("systemctl", args...).CombinedOutput()
	return strings.TrimSpace(string(out)), err
}

func DaemonReload() error {
	_, err := systemctl("daemon-reload")
	return err
}

const unitStateTTL = 2 * time.Second
const unitStatePrune = 5 * time.Minute

var unitCache = newTTLCache[bool](unitStateTTL, unitStatePrune)

func IsActive(service string) bool {
	return unitCache.get("is-active\x00"+service, func() bool {
		out, _ := systemctl("is-active", service)
		return out == "active"
	})
}

func IsEnabled(service string) bool {
	out, _ := systemctl("is-enabled", service)
	return out == "enabled"
}

func StartService(service string) error {
	_, err := systemctl("enable", "--now", service)
	unitCache.forget()
	return err
}

func StopService(service string) error {
	_, err := systemctl("stop", service)
	unitCache.forget()
	return err
}

func RestartService(service string) error {
	_, err := systemctl("restart", service)
	unitCache.forget()
	return err
}

func DisableService(service string) error {
	_, err := systemctl("disable", "--now", service)
	unitCache.forget()
	return err
}

func EnsureUnits() int {
	n := 0
	for _, t := range List() {
		path := app.ServiceDir + "/" + app.ServiceName(t.Name)
		want := unitFor(t.Name)
		if have, err := os.ReadFile(path); err == nil && string(have) == want {
			continue
		}
		if os.WriteFile(path, []byte(want), 0644) == nil {
			n++
		}
	}
	if n > 0 {
		_ = DaemonReload()
	}
	return n
}

func writeUnit(name string) error {
	path := app.ServiceDir + "/" + app.ServiceName(name)
	return os.WriteFile(path, []byte(unitFor(name)), 0644)
}

func unitFor(name string) string {
	return fmt.Sprintf(`[Unit]
Description=ParsTanel Tunnel (%s)
After=network.target

[Service]
Type=simple
ExecStart=%s -c %s
Restart=always
RestartSec=3
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
`, name, app.BinPath, app.ConfigPath(name))
}

func removeUnit(name string) {
	os.Remove(app.ServiceDir + "/" + app.ServiceName(name))
}

func FollowLog(service string) error {
	cmd := exec.Command("journalctl", "-u", service, "-n", "200", "-f", "--no-pager")
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}

	if err := cmd.Start(); err != nil {
		return err
	}

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	done := make(chan struct{})
	go func() {
		select {
		case <-sig:
			_ = cmd.Process.Kill()
		case <-done:
		}
	}()

	err := cmd.Wait()
	close(done)
	signal.Stop(sig)
	return err
}