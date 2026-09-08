package manage

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

func localUpdateDirs() []string { return localUpdateDirsFn() }

var localUpdateDirsFn = func() []string {
	return []string{"/root", app.InstallDir, "."}
}

func LocalAssetName() string {
	return fmt.Sprintf("parstanel_linux_%s.tar.gz", runtime.GOARCH)
}

type LocalUpdate struct {
	Path      string
	Size      int64
	When      time.Time
	Version   string
	Checksums string
}

func FindLocalUpdate() (LocalUpdate, bool) {
	name := LocalAssetName()
	for _, dir := range localUpdateDirs() {
		path := filepath.Join(dir, name)
		fi, err := os.Stat(path)
		if err != nil || fi.IsDir() || fi.Size() == 0 {
			continue
		}
		u := LocalUpdate{Path: path, Size: fi.Size(), When: fi.ModTime()}
		if sums := filepath.Join(dir, "SHA256SUMS"); fileExists(sums) {
			u.Checksums = sums
		}
		u.Version = versionInArchive(path)
		return u, true
	}
	return LocalUpdate{}, false
}

func LocalUpdateSearchedIn() []string { return localUpdateDirs() }

func versionInArchive(archive string) string {
	tmp, err := os.CreateTemp("", "parstanel-check-*")
	if err != nil {
		return ""
	}
	path := tmp.Name()
	tmp.Close()
	defer os.Remove(path)

	if err := extractBinaryTo(archive, path); err != nil {
		return ""
	}
	if err := os.Chmod(path, 0755); err != nil {
		return ""
	}
	out, err := runBounded(path, 5*time.Second, "-v")
	if err != nil {
		return ""
	}
	v := strings.TrimSpace(out)
	if v == "" || len(v) > 32 || strings.ContainsAny(v, "\n\r") {
		return ""
	}
	return v
}

func runBounded(bin string, d time.Duration, args ...string) (string, error) {
	cmd := exec.Command(bin, args...)
	var out strings.Builder
	cmd.Stdout = &out
	if err := cmd.Start(); err != nil {
		return "", err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		return out.String(), err
	case <-time.After(d):
		_ = cmd.Process.Kill()
		<-done
		return "", fmt.Errorf("it did not answer in %s", d)
	}
}

func ApplyLocalUpdate(u LocalUpdate, logf func(string)) error {
	if logf == nil {
		logf = func(string) {}
	}
	if !fileExists(u.Path) {
		return fmt.Errorf("%s is not there any more", u.Path)
	}

	if u.Checksums != "" {
		sums, err := os.ReadFile(u.Checksums)
		if err != nil {
			return fmt.Errorf("could not read %s: %w", u.Checksums, err)
		}
		want := hashFor(string(sums), filepath.Base(u.Path))
		if want == "" {
			return fmt.Errorf("%s says nothing about %s — remove it, or download the matching one", u.Checksums, filepath.Base(u.Path))
		}
		if err := verifyChecksum(u.Path, want); err != nil {
			return fmt.Errorf("%s does not match %s: %w", filepath.Base(u.Path), u.Checksums, err)
		}
		logf("Checksum verified against " + u.Checksums + ".")
	} else {
		logf("No SHA256SUMS beside the archive — installing it unverified.")
	}

	logf("Taking a safety snapshot...")
	snap, err := TakeSnapshot("pre-update")
	if err != nil {
		return fmt.Errorf("could not take a safety snapshot: %w", err)
	}
	logf("Snapshot saved: " + filepath.Base(snap.Dir))

	what := u.Version
	if what == "" {
		what = filepath.Base(u.Path)
	}
	logf("Installing " + what + "...")
	if err := extractBinary(u.Path); err != nil {
		return err
	}

	_ = os.MkdirAll(app.BackupDir, 0755)
	if InstallPath() == "" {
		_ = os.MkdirAll(app.ConfigDir, 0755)
		_ = os.WriteFile(app.InstallPathFile, []byte(app.InstallDir+"\n"), 0644)
	}

	logf("Restarting services...")
	if err := RestartMonitorService(); err != nil {
		logf("Warning: monitor service could not start: " + err.Error())
	}
	ok, failed := RestartAll()
	logf(fmt.Sprintf("Restarted %d tunnels (%d failed).", ok, failed))

	logf("Checking health...")
	if bad := unhealthyAfterUpdate(); len(bad) > 0 {
		logf("Health check FAILED for: " + strings.Join(bad, ", "))
		logf("Rolling back to the previous version...")
		if rerr := RestoreSnapshot(snap, logf); rerr != nil {
			return fmt.Errorf("update failed AND rollback failed: %v (rollback: %v) — restore manually from %s", strings.Join(bad, ", "), rerr, snap.Dir)
		}
		return fmt.Errorf("the update failed its health check (%s) — rolled back to %s. %s was left in place", strings.Join(bad, ", "), snap.Meta.Version, u.Path)
	}
	logf("Health check passed.")

	if err := os.Remove(u.Path); err != nil {
		logf("Warning: could not remove " + u.Path + ": " + err.Error())
	} else {
		logf("Removed " + u.Path + ".")
	}

	if u.Checksums != "" {
		if sums, err := os.ReadFile(u.Checksums); err == nil && !namesAnotherFile(string(sums), u) {
			_ = os.Remove(u.Checksums)
		}
	}

	logf("Update complete — now running " + installedVersion() + ".")
	return nil
}

func installedVersion() string {
	out, err := runBounded(app.BinPath, 5*time.Second, "-v")
	if err != nil {
		return "the new version"
	}
	if v := strings.TrimSpace(out); v != "" {
		return v
	}
	return "the new version"
}

func namesAnotherFile(sums string, u LocalUpdate) bool {
	dir := filepath.Dir(u.Checksums)
	installed := filepath.Base(u.Path)
	for _, line := range strings.Split(sums, "\n") {
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		name := strings.TrimPrefix(fields[len(fields)-1], "*")
		if name == installed {
			continue
		}
		if fileExists(filepath.Join(dir, name)) {
			return true
		}
	}
	return false
}