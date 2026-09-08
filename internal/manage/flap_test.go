package manage

import (
	"strings"
	"testing"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/alerthist"
)

func withTempAlerts(t *testing.T) {
	t.Helper()
	old := alerthist.Dir
	alerthist.Dir = t.TempDir()
	t.Cleanup(func() { alerthist.Dir = old })
}

func messages(t *testing.T) []string {
	t.Helper()
	var out []string
	for _, e := range alerthist.Load().Events {
		out = append(out, e.Message)
	}
	return out
}

func countWith(msgs []string, sub string) int {
	n := 0
	for _, m := range msgs {
		if strings.Contains(m, sub) {
			n++
		}
	}
	return n
}

func TestAnOccasionalRestartIsReportedOnItsOwn(t *testing.T) {
	withTempAlerts(t)

	now := time.Now()
	var at []time.Time
	last := map[string]time.Time{}
	for i := 0; i < flapThreshold-1; i++ {
		at = recentRestarts(at, now)
		reportRestart("iran-main", at, last, now)
		now = now.Add(5 * time.Minute)
	}

	msgs := messages(t)
	if got := countWith(msgs, "Watchdog restarted"); got != flapThreshold-1 {
		t.Errorf("reported %d individual restarts, want %d", got, flapThreshold-1)
	}
	if countWith(msgs, "flapping") != 0 {
		t.Error("called it flapping before it was")
	}
}

func TestSustainedRestartsBecomeOneFinding(t *testing.T) {
	withTempAlerts(t)

	now := time.Now()
	var at []time.Time
	last := map[string]time.Time{}
	for i := 0; i < 20; i++ {
		at = recentRestarts(at, now)
		reportRestart("iran-main", at, last, now)
		now = now.Add(3 * time.Minute)
	}

	msgs := messages(t)
	flaps := countWith(msgs, "flapping")
	if flaps == 0 {
		t.Fatal("twenty restarts in an hour were never called flapping")
	}
	if flaps > 2 {
		t.Errorf("reported flapping %d times; it is one condition, stated once a window", flaps)
	}
	if got := countWith(msgs, "Watchdog restarted"); got >= 20 {
		t.Errorf("still emitted %d individual restart lines", got)
	}
	var flapMsg string
	for _, m := range msgs {
		if strings.Contains(m, "flapping") {
			flapMsg = m
			break
		}
	}
	if !strings.Contains(flapMsg, "MSS") {
		t.Errorf("the flapping report suggests nothing to check: %q", flapMsg)
	}
}

func TestOldRestartsFallOutOfTheWindow(t *testing.T) {
	now := time.Now()
	old := []time.Time{
		now.Add(-2 * flapWindow),
		now.Add(-flapWindow - time.Minute),
		now.Add(-time.Minute),
	}

	got := recentRestarts(old, now)
	if len(got) != 2 {
		t.Fatalf("kept %d restarts, want the 1 still inside the window plus the new one", len(got))
	}
	for _, at := range got {
		if now.Sub(at) >= flapWindow {
			t.Errorf("kept a restart from %s ago, outside the %s window", now.Sub(at), flapWindow)
		}
	}
}

func TestFlappingIsRestatedEachWindow(t *testing.T) {
	withTempAlerts(t)

	now := time.Now()
	last := map[string]time.Time{}
	for day := 0; day < 3; day++ {
		var at []time.Time
		for i := 0; i < flapThreshold+2; i++ {
			at = recentRestarts(at, now)
			reportRestart("iran-main", at, last, now)
			now = now.Add(4 * time.Minute)
		}
		now = now.Add(flapWindow)
	}

	if got := countWith(messages(t), "flapping"); got < 3 {
		t.Errorf("three separate episodes produced %d reports", got)
	}
}