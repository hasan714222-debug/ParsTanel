package manage

import (
	"context"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/alerthist"
	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

// Weekly automatic backups.
const autoBackupEvery = 7 * 24 * time.Hour

var autoBackupFlag = app.ConfigDir + "/autobackup"

func AutoBackupEnabled() bool {
	_, err := os.Stat(autoBackupFlag)
	return err == nil
}

func SetAutoBackup(on bool) error {
	if !on {
		err := os.Remove(autoBackupFlag)
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	if err := os.MkdirAll(app.ConfigDir, 0755); err != nil {
		return err
	}
	return os.WriteFile(autoBackupFlag, []byte("weekly\n"), 0644)
}

func newestBackupTime() time.Time {
	matches, _ := filepath.Glob(filepath.Join(app.BackupDir, "parstanel-backup-*.tar.gz"))
	if len(matches) == 0 {
		return time.Time{}
	}
	sort.Strings(matches)
	fi, err := os.Stat(matches[len(matches)-1])
	if err != nil {
		return time.Time{}
	}
	return fi.ModTime()
}

func RunAutoBackup(ctx context.Context) {
	t := time.NewTicker(time.Hour)
	defer t.Stop()
	for {
		autoBackupPass()
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}

func autoBackupPass() {
	if !AutoBackupEnabled() {
		return
	}
	if last := newestBackupTime(); !last.IsZero() && time.Since(last) < autoBackupEvery {
		return
	}
	path, err := BackupToFile(app.BackupDir)
	if err != nil {
		alerthist.RecordEvent("💾 Weekly auto-backup FAILED: " + err.Error())
		return
	}
	alerthist.RecordEvent("💾 Weekly auto-backup saved: " + filepath.Base(path))
}