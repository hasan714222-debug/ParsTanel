package manage

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

var UpdateStateFile = app.ConfigDir + "/update_check.json"

type UpdateState struct {
	Tag      string    `json:"tag"`
	Checked  time.Time `json:"checked"`
	Notified string    `json:"notified"`
}

var updateStateMu sync.Mutex

func loadUpdateState() UpdateState {
	updateStateMu.Lock()
	defer updateStateMu.Unlock()
	return loadUpdateStateLocked()
}

func loadUpdateStateLocked() UpdateState {
	var s UpdateState
	data, err := os.ReadFile(UpdateStateFile)
	if err != nil {
		return s
	}
	json.Unmarshal(data, &s)
	return s
}

func saveUpdateStateLocked(s UpdateState) error {
	dir := filepath.Dir(UpdateStateFile)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	data, _ := json.MarshalIndent(s, "", "  ")

	tmp, err := os.CreateTemp(dir, ".update_check-*.tmp")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)

	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(name, 0644); err != nil {
		return err
	}
	return os.Rename(name, UpdateStateFile)
}

func UpdateAvailable() (string, bool) {
	s := loadUpdateState()
	if s.Tag == "" || !newerVersion(s.Tag, app.Version) {
		return "", false
	}
	return s.Tag, true
}

func refreshUpdateCheck() {
	tag, err := latestTag()
	if err != nil || tag == "" {
		return
	}

	updateStateMu.Lock()
	defer updateStateMu.Unlock()
	s := loadUpdateStateLocked()
	s.Tag = tag
	s.Checked = time.Now()
	saveUpdateStateLocked(s)
}

func RefreshUpdateCheckIfStale(maxAge time.Duration) {
	if time.Since(loadUpdateState().Checked) < maxAge {
		return
	}
	refreshUpdateCheck()
}

func MarkUpdateNotified(tag string) {
	updateStateMu.Lock()
	defer updateStateMu.Unlock()
	s := loadUpdateStateLocked()
	s.Notified = tag
	saveUpdateStateLocked(s)
}

func UpdateNeedsNotifying() (string, bool) {
	tag, ok := UpdateAvailable()
	if !ok {
		return "", false
	}
	if loadUpdateState().Notified == tag {
		return "", false
	}
	return tag, true
}
