package manage

import (
	"archive/tar"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/schedule"
)

const backupMetaName = ".parstanel-backup.json"

type backupMeta struct {
	Version          string `json:"version"`
	Created          string `json:"created"`
	AutoRefreshHours int    `json:"auto_refresh_hours"`
}

type RestoreResult struct {
	Files            int
	Tunnels          []string
	Started          int
	Failed           int
	WebUIConfig      bool
	TelegramConfig   bool
	AutoRefreshHours int
}

func WriteBackup(w io.Writer) error { return writeBackupTree(w, app.ConfigDir) }

func writeBackupTree(w io.Writer, root string) error {
	gz := gzip.NewWriter(w)
	tw := tar.NewWriter(gz)

	if err := writeBackupEntries(tw, root); err != nil {
		tw.Close()
		gz.Close()
		return err
	}

	if err := tw.Close(); err != nil {
		gz.Close()
		return fmt.Errorf("finishing the archive: %w", err)
	}
	if err := gz.Close(); err != nil {
		return fmt.Errorf("finishing compression: %w", err)
	}
	return nil
}

func writeBackupEntries(tw *tar.Writer, root string) error {
	meta := backupMeta{
		Version:          app.Version,
		Created:          time.Now().UTC().Format(time.RFC3339),
		AutoRefreshHours: schedule.AutoRefreshHours(),
	}
	metaJSON, err := json.MarshalIndent(meta, "", "  ")
	if err != nil {
		return fmt.Errorf("describing the backup: %w", err)
	}
	if err := tw.WriteHeader(&tar.Header{
		Name: backupMetaName,
		Mode: 0600,
		Size: int64(len(metaJSON)),
	}); err != nil {
		return err
	}
	if _, err := tw.Write(metaJSON); err != nil {
		return err
	}

	return filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}

		if !info.IsDir() && !info.Mode().IsRegular() {
			return fmt.Errorf("refusing to back up %s: not a regular file (%s)", rel, info.Mode().Type())
		}

		hdr, err := tar.FileInfoHeader(info, "")
		if err != nil {
			return err
		}
		hdr.Name = filepath.ToSlash(rel)
		if info.IsDir() {
			hdr.Name += "/"
			return tw.WriteHeader(hdr)
		}
		if err := tw.WriteHeader(hdr); err != nil {
			return err
		}
		return copyFileInto(tw, path)
	})
}

func copyFileInto(tw *tar.Writer, path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	_, err = io.Copy(tw, f)
	return err
}

const backupRetention = 10
const partialAge = time.Hour

func pruneBackups(dir string) {
	sweepPartials(dir)

	matches, _ := filepath.Glob(filepath.Join(dir, "parstanel-backup-*.tar.gz"))
	if len(matches) <= backupRetention {
		return
	}
	sort.Sort(sort.Reverse(sort.StringSlice(matches)))
	for _, old := range matches[backupRetention:] {
		os.Remove(old)
	}
}

func sweepPartials(dir string) {
	matches, _ := filepath.Glob(filepath.Join(dir, ".parstanel-backup-*.partial"))
	for _, path := range matches {
		info, err := os.Stat(path)
		if err != nil || time.Since(info.ModTime()) < partialAge {
			continue
		}
		os.Remove(path)
	}
}

func publishBackup(dir string, write func(io.Writer) error) (string, error) {
	if err := os.MkdirAll(dir, 0755); err != nil {
		return "", err
	}

	tmp, err := os.CreateTemp(dir, ".parstanel-backup-*.partial")
	if err != nil {
		return "", err
	}
	tmpPath := tmp.Name()
	defer func() {
		if tmpPath != "" {
			tmp.Close()
			os.Remove(tmpPath)
		}
	}()

	if err := tmp.Chmod(0600); err != nil {
		return "", err
	}
	if err := write(tmp); err != nil {
		return "", err
	}
	if err := tmp.Sync(); err != nil {
		return "", err
	}
	if err := tmp.Close(); err != nil {
		return "", err
	}

	path, err := freeBackupPath(dir)
	if err != nil {
		return "", err
	}
	if err := os.Rename(tmpPath, path); err != nil {
		return "", err
	}
	tmpPath = ""

	syncDir(dir)
	pruneBackups(dir)
	return path, nil
}

func freeBackupPath(dir string) (string, error) {
	stamp := time.Now().Format("20060102-150405")
	for n := 0; n < 100; n++ {
		name := fmt.Sprintf("parstanel-backup-%s.tar.gz", stamp)
		if n > 0 {
			name = fmt.Sprintf("parstanel-backup-%s-%d.tar.gz", stamp, n)
		}
		path := filepath.Join(dir, name)
		if _, err := os.Stat(path); os.IsNotExist(err) {
			return path, nil
		}
	}
	return "", fmt.Errorf("could not find an unused backup name in %s", dir)
}

func BackupToFile(dir string) (string, error) {
	return publishBackup(dir, WriteBackup)
}

func syncDir(dir string) {
	d, err := os.Open(dir)
	if err != nil {
		return
	}
	defer d.Close()
	_ = d.Sync()
}

func Restore(r io.Reader) (RestoreResult, error) {
	var res RestoreResult

	if err := os.MkdirAll(app.ConfigDir, 0755); err != nil {
		return res, err
	}

	stage, err := os.MkdirTemp(filepath.Dir(app.ConfigDir), ".parstanel-restore-*")
	if err != nil {
		return res, err
	}
	defer os.RemoveAll(stage)

	contents, err := stageRestore(r, app.ConfigDir, stage)
	if err != nil {
		return res, err
	}
	if err := commitRestore(app.ConfigDir, stage); err != nil {
		return res, err
	}

	res.Files = contents.Files
	res.WebUIConfig = contents.WebUIConfig
	res.TelegramConfig = contents.TelegramConfig
	res.AutoRefreshHours = contents.AutoRefreshHours
	sawConfig := contents.SawTunnelConfig

	if sawConfig {
		tunnels := List()
		unitFailed := map[string]bool{}
		for _, t := range tunnels {
			res.Tunnels = append(res.Tunnels, t.Name)
			if err := writeUnit(t.Name); err != nil {
				unitFailed[t.Name] = true
			}
		}
		_ = DaemonReload()
		for _, t := range tunnels {
			if unitFailed[t.Name] {
				res.Failed++
				continue
			}
			if err := StartService(app.ServiceName(t.Name)); err != nil {
				res.Failed++
				continue
			}
			if err := RestartService(app.ServiceName(t.Name)); err != nil {
				res.Failed++
				continue
			}
			res.Started++
		}
	}

	if res.AutoRefreshHours > 0 {
		_ = schedule.SetAutoRefresh(res.AutoRefreshHours)
	}

	return res, nil
}
