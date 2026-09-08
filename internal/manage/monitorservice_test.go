package manage

import (
	"os"
	"strings"
	"testing"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

func TestMonitorUnitContents(t *testing.T) {
	unit := strings.ReplaceAll(monitorUnit, "%s", app.BinPath)

	if !strings.Contains(unit, app.BinPath+" --monitor") {
		t.Errorf("ExecStart does not invoke the monitor mode:\n%s", unit)
	}
	if !strings.Contains(unit, "Restart=always") {
		t.Errorf("the unit does not restart automatically:\n%s", unit)
	}
	if !strings.Contains(unit, "WantedBy=multi-user.target") {
		t.Errorf("the unit would not start at boot:\n%s", unit)
	}
}

func TestMonitorFlagIsParsed(t *testing.T) {
	src, err := os.ReadFile("../../main.go")
	if err != nil {
		t.Skipf("cannot read main.go: %v", err)
	}
	if !strings.Contains(string(src), `flag.Bool("monitor"`) {
		t.Error(`main.go does not define a "monitor" flag, so the service would fall through to the interactive menu`)
	}
}

func TestMonitorServiceNameIsValid(t *testing.T) {
	if !strings.HasSuffix(app.MonitorService, ".service") {
		t.Errorf("%q is not a systemd unit name", app.MonitorService)
	}
}

func TestUpdateRestartsTheMonitor(t *testing.T) {
	src, err := os.ReadFile("update.go")
	if err != nil {
		t.Skipf("cannot read update.go: %v", err)
	}
	if !strings.Contains(string(src), "RestartMonitorService()") {
		t.Error("ApplyUpdate does not restart the monitor, so it would keep running the old binary")
	}
}

func TestRollbackRestartsTheMonitor(t *testing.T) {
	src, err := os.ReadFile("snapshot.go")
	if err != nil {
		t.Skipf("cannot read snapshot.go: %v", err)
	}
	if !strings.Contains(string(src), "RestartMonitorService()") {
		t.Error("a rollback does not restart the monitor, leaving it on the version that failed")
	}
}

func TestUpdateHealthCheckCoversTheMonitor(t *testing.T) {
	src, err := os.ReadFile("update.go")
	if err != nil {
		t.Skipf("cannot read update.go: %v", err)
	}
	body := string(src)
	i := strings.Index(body, "func unhealthyAfterUpdate")
	if i < 0 {
		t.Fatal("unhealthyAfterUpdate not found — this test needs updating")
	}
	if !strings.Contains(body[i:], "MonitorService") {
		t.Error("the post-update health check ignores the monitor service")
	}
}

func TestRestoreRestartsTunnels(t *testing.T) {
	src, err := os.ReadFile("backup.go")
	if err != nil {
		t.Skipf("cannot read backup.go: %v", err)
	}
	body := string(src)

	i := strings.Index(body, "func Restore(")
	if i < 0 {
		t.Fatal("Restore not found — this test needs updating")
	}
	if !strings.Contains(body[i:], "RestartService(") {
		t.Error("Restore only starts tunnels, so running ones would keep their old configuration")
	}
}