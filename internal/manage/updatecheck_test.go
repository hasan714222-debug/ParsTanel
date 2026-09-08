package manage

import (
	"testing"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

func withTempState(t *testing.T) {
	t.Helper()
	orig := UpdateStateFile
	UpdateStateFile = t.TempDir() + "/update_check.json"
	t.Cleanup(func() { UpdateStateFile = orig })
}

func TestNoCacheMeansNoNotice(t *testing.T) {
	withTempState(t)
	if tag, ok := UpdateAvailable(); ok {
		t.Fatalf("a missing cache must not claim an update, got %q", tag)
	}
}

func TestSameVersionIsNotAnUpdate(t *testing.T) {
	withTempState(t)
	updateStateMu.Lock()
	saveUpdateStateLocked(UpdateState{Tag: app.Version, Checked: time.Now()})
	updateStateMu.Unlock()

	if tag, ok := UpdateAvailable(); ok {
		t.Fatalf("the running version is not an update, got %q", tag)
	}
}

func TestOlderVersionIsNotAnUpdate(t *testing.T) {
	withTempState(t)
	updateStateMu.Lock()
	saveUpdateStateLocked(UpdateState{Tag: "v0.0.1", Checked: time.Now()})
	updateStateMu.Unlock()

	if tag, ok := UpdateAvailable(); ok {
		t.Fatalf("an older release is not an update, got %q", tag)
	}
}

func TestNewerVersionIsReported(t *testing.T) {
	withTempState(t)
	updateStateMu.Lock()
	saveUpdateStateLocked(UpdateState{Tag: "v99.0.0", Checked: time.Now()})
	updateStateMu.Unlock()

	tag, ok := UpdateAvailable()
	if !ok || tag != "v99.0.0" {
		t.Fatalf("UpdateAvailable() = %q, %v; want v99.0.0, true", tag, ok)
	}
}

func TestNotifiedOnlyOnce(t *testing.T) {
	withTempState(t)
	updateStateMu.Lock()
	saveUpdateStateLocked(UpdateState{Tag: "v99.0.0", Checked: time.Now()})
	updateStateMu.Unlock()

	tag, ok := UpdateNeedsNotifying()
	if !ok || tag != "v99.0.0" {
		t.Fatalf("first call should want to notify about v99.0.0, got %q, %v", tag, ok)
	}
	MarkUpdateNotified(tag)

	for i := 0; i < 3; i++ {
		if tag, ok := UpdateNeedsNotifying(); ok {
			t.Fatalf("call %d wanted to notify again about %q", i+2, tag)
		}
	}
}

func TestNewerReleaseAfterNotifyIsAnnounced(t *testing.T) {
	withTempState(t)
	updateStateMu.Lock()
	saveUpdateStateLocked(UpdateState{Tag: "v99.0.0", Checked: time.Now()})
	updateStateMu.Unlock()

	tag, _ := UpdateNeedsNotifying()
	MarkUpdateNotified(tag)

	updateStateMu.Lock()
	s := loadUpdateStateLocked()
	s.Tag = "v99.1.0"
	saveUpdateStateLocked(s)
	updateStateMu.Unlock()

	got, ok := UpdateNeedsNotifying()
	if !ok || got != "v99.1.0" {
		t.Fatalf("a newer release should be announced, got %q, %v", got, ok)
	}
}

func TestFailedRefreshKeepsPreviousAnswer(t *testing.T) {
	if testing.Short() {
		t.Skip("reaches the network — skipped under -short")
	}
	withTempState(t)
	updateStateMu.Lock()
	saveUpdateStateLocked(UpdateState{Tag: "v99.0.0", Checked: time.Now(), Notified: "v98.0.0"})
	updateStateMu.Unlock()

	before := loadUpdateState()

	refreshUpdateCheck()

	after := loadUpdateState()
	if after.Tag != before.Tag && after.Tag == "" {
		t.Fatalf("a failed check erased the cached tag: %q -> %q", before.Tag, after.Tag)
	}
	if after.Notified != before.Notified {
		t.Errorf("a check must not disturb the notified mark: %q -> %q", before.Notified, after.Notified)
	}
}

func TestRefreshIfStaleSkipsFreshAnswers(t *testing.T) {
	withTempState(t)
	fresh := time.Now()
	updateStateMu.Lock()
	saveUpdateStateLocked(UpdateState{Tag: "v99.0.0", Checked: fresh})
	updateStateMu.Unlock()

	RefreshUpdateCheckIfStale(time.Hour)

	if got := loadUpdateState().Checked; !got.Equal(fresh.Truncate(0)) && got.Sub(fresh).Abs() > time.Second {
		t.Errorf("a fresh answer should not have been refreshed (checked moved from %v to %v)", fresh, got)
	}
}
