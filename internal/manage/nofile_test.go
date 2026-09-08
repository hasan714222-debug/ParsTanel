package manage

import (
	"os"
	"strings"
	"testing"
)

func TestEveryServiceUnitAsksForItsOpenFileLimit(t *testing.T) {
	for _, c := range []struct{ file, what string }{
		{"systemd.go", "the tunnel"},
		{"monitorservice.go", "the monitor"},
		{"proxyservice.go", "the proxy"},
	} {
		b, err := os.ReadFile(c.file)
		if err != nil {
			t.Fatalf("cannot read %s: %v", c.file, err)
		}
		src := string(b)
		if !strings.Contains(src, "[Service]") {
			t.Fatalf("%s no longer holds a unit — this guard needs updating", c.file)
		}
		if !strings.Contains(src, "LimitNOFILE=") {
			t.Errorf("%s installs %s with no LimitNOFILE", c.file, c.what)
		}
	}
}

func TestTheOpenFileCheckMeasuresTheTunnels(t *testing.T) {
	b, err := os.ReadFile("diagnose.go")
	if err != nil {
		t.Fatalf("cannot read diagnose.go: %v", err)
	}
	src := string(b)

	if strings.Contains(src, `"ulimit -n"`) {
		t.Error("the open-file check reads this process's own limit again")
	}
	if !strings.Contains(src, "/proc/%d/limits") {
		t.Error("the check no longer reads a running tunnel's real limit from /proc")
	}
	i := strings.Index(src, `Name: "Open file limit"`)
	if i < 0 {
		t.Fatal("the open-file check is gone — this guard needs updating")
	}
	near := src[i:min(len(src), i+900)]
	if strings.Contains(near, "run Optimize, then reboot") {
		t.Error("the fix still tells the operator to run Optimize and reboot")
	}
}

func TestTheUnitItComparesAgainstIsTheOneItWould(t *testing.T) {
	want := unitFor("nl-ws")
	if !strings.Contains(want, "LimitNOFILE=") {
		t.Error("the tunnel unit no longer asks for an open-file limit")
	}
	if !strings.Contains(want, "ParsTanel Tunnel (nl-ws)") {
		t.Error("unitFor no longer produces the tunnel's own unit")
	}

	src, err := os.ReadFile("systemd.go")
	if err != nil {
		t.Fatalf("cannot read systemd.go: %v", err)
	}
	body := string(src)

	for _, fn := range []string{"func writeUnit(", "func EnsureUnits("} {
		i := strings.Index(body, fn)
		if i < 0 {
			t.Fatalf("%s is gone — this guard needs updating", fn)
		}
		f := body[i:]
		if end := strings.Index(f, "\n}\n"); end > 0 {
			f = f[:end]
		}
		if !strings.Contains(f, "unitFor(") {
			t.Errorf("%s builds its own unit text instead of using unitFor", fn)
		}
	}

	menu, err := os.ReadFile("../menu/menu.go")
	if err != nil {
		t.Fatalf("cannot read menu.go: %v", err)
	}
	if !strings.Contains(string(menu), "EnsureUnits()") {
		t.Error("nothing brings stale tunnel units up to date")
	}
}
