package manage

import (
	"archive/tar"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

const (
	maxRestoreEntries   = 10_000
	maxRestoreFileBytes = 64 << 20
	maxRestoreBytes     = 256 << 20
)

type restoreContents struct {
	Files            int
	WebUIConfig      bool
	TelegramConfig   bool
	SawTunnelConfig  bool
	AutoRefreshHours int
}

func stageRestore(r io.Reader, configDir, stage string) (restoreContents, error) {
	var contents restoreContents

	if err := seedStage(configDir, stage); err != nil {
		return contents, err
	}

	gz, err := gzip.NewReader(r)
	if err != nil {
		return contents, fmt.Errorf("not a valid backup archive: %w", err)
	}
	defer gz.Close()

	tr := tar.NewReader(gz)
	seen := make(map[string]bool)
	var total int64

	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return contents, fmt.Errorf("reading archive: %w", err)
		}

		if hdr.Name == backupMetaName {
			var m backupMeta
			if data, err := io.ReadAll(io.LimitReader(tr, maxRestoreFileBytes)); err == nil {
				_ = json.Unmarshal(data, &m)
				contents.AutoRefreshHours = m.AutoRefreshHours
			}
			continue
		}

		name, err := safeRestoreName(hdr.Name)
		if err != nil {
			return contents, err
		}
		if seen[name] {
			return contents, fmt.Errorf("archive names %q more than once", hdr.Name)
		}
		seen[name] = true
		if len(seen) > maxRestoreEntries {
			return contents, fmt.Errorf("archive holds more than %d entries", maxRestoreEntries)
		}

		if installPath := filepath.Base(app.InstallPathFile); name == installPath && fileExists(filepath.Join(configDir, installPath)) {
			continue
		}

		target := filepath.Join(stage, name)
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0755); err != nil {
				return contents, err
			}

		case tar.TypeReg:
			if hdr.Size > maxRestoreFileBytes {
				return contents, fmt.Errorf("%s is %d bytes, over the %d-byte limit for one file", name, hdr.Size, int64(maxRestoreFileBytes))
			}
			total += hdr.Size
			if total > maxRestoreBytes {
				return contents, fmt.Errorf("archive expands to more than %d bytes", int64(maxRestoreBytes))
			}
			if err := writeStagedFile(target, tr, hdr); err != nil {
				return contents, err
			}
			contents.Files++
			noteRestoredFile(&contents, name)

		default:
			return contents, fmt.Errorf("refusing %q: a backup holds only files and directories", hdr.Name)
		}
	}

	if _, err := io.Copy(io.Discard, gz); err != nil {
		return contents, fmt.Errorf("the archive is corrupt or truncated: %w", err)
	}

	return contents, nil
}

func writeStagedFile(target string, r io.Reader, hdr *tar.Header) error {
	if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
		return err
	}
	mode := os.FileMode(hdr.Mode).Perm()
	if mode == 0 {
		mode = 0600
	}
	f, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	if _, err := io.Copy(f, io.LimitReader(r, maxRestoreFileBytes+1)); err != nil {
		f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Chmod(target, mode)
}

func noteRestoredFile(contents *restoreContents, name string) {
	base := filepath.Base(name)
	if strings.HasSuffix(base, ".toml") {
		contents.SawTunnelConfig = true
	}
}

func safeRestoreName(name string) (string, error) {
	refuse := func() (string, error) {
		return "", fmt.Errorf("refusing unsafe path in archive: %q", name)
	}
	if name == "" || strings.ContainsRune(name, '\\') || strings.ContainsRune(name, 0) {
		return refuse()
	}
	if filepath.IsAbs(name) || strings.HasPrefix(name, "/") || filepath.VolumeName(name) != "" {
		return refuse()
	}

	clean := filepath.Clean(filepath.FromSlash(name))
	if clean == "." || clean == ".." || filepath.IsAbs(clean) {
		return refuse()
	}
	for _, element := range strings.Split(clean, string(filepath.Separator)) {
		if element == ".." {
			return refuse()
		}
	}
	return clean, nil
}

func seedStage(configDir, stage string) error {
	return filepath.Walk(configDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(configDir, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		target := filepath.Join(stage, rel)

		switch {
		case info.IsDir():
			return os.MkdirAll(target, info.Mode().Perm())
		case info.Mode().IsRegular():
			return copyFileTo(path, target, info.Mode().Perm())
		default:
			return fmt.Errorf("cannot restore over %s: it is not a regular file (%s)", rel, info.Mode().Type())
		}
	})
}

func copyFileTo(source, target string, mode os.FileMode) error {
	in, err := os.Open(source)
	if err != nil {
		return err
	}
	defer in.Close()

	if err := os.MkdirAll(filepath.Dir(target), 0755); err != nil {
		return err
	}
	out, err := os.OpenFile(target, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	if err := out.Close(); err != nil {
		return err
	}
	return os.Chmod(target, mode)
}

func commitRestore(configDir, stage string) error {
	mode := os.FileMode(0755)
	if info, err := os.Stat(configDir); err == nil {
		mode = info.Mode().Perm()
	}
	if err := os.Chmod(stage, mode); err != nil {
		return err
	}

	previous := configDir + ".restore-previous"
	os.RemoveAll(previous)

	if err := os.Rename(configDir, previous); err != nil {
		return fmt.Errorf("could not move the current configuration aside: %w", err)
	}
	if err := os.Rename(stage, configDir); err != nil {
		if back := os.Rename(previous, configDir); back != nil {
			return fmt.Errorf("could not restore configuration (%v) nor rollback; see %s: %w", err, previous, back)
		}
		return fmt.Errorf("could not place restored configuration, previous kept: %w", err)
	}

	syncDir(filepath.Dir(configDir))
	os.RemoveAll(previous)
	return nil
}
