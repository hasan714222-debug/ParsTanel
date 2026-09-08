package manage

import (
	"archive/tar"
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/BurntSushi/toml"
	"github.com/hasan714222-debug/ParsTanel/config"
	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/socks"
)

func repoURL() string {
	return fmt.Sprintf("https://github.com/%s/%s", app.RepoOwner, app.RepoName)
}

func InstallPath() string {
	b, err := os.ReadFile(app.InstallPathFile)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(b))
}

func relayHTTPClient(timeout time.Duration) *http.Client {
	matches, _ := filepath.Glob(app.ConfigDir + "/*.toml")
	for _, path := range matches {
		var cfg config.Config
		if _, err := toml.DecodeFile(path, &cfg); err != nil || cfg.Server.BindAddr == "" {
			continue
		}
		if port := relayExposedPort(cfg.Server.Ports, cfg.Server.Token); port != "" {
			return socks.HTTPClient("127.0.0.1:"+port, "parstanel", cfg.Server.Token, timeout)
		}
	}
	return nil
}

func relayExposedPort(ports []string, token string) string {
	for _, suffix := range []string{
		fmt.Sprintf("=127.0.0.1:%d", app.SocksInternalPort),
		fmt.Sprintf("=127.0.0.1:%d", app.SocksPortForToken(token)),
	} {
		for _, p := range ports {
			p = strings.TrimSpace(p)
			if !strings.HasSuffix(p, suffix) {
				continue
			}
			port := strings.TrimSuffix(p, suffix)
			if i := strings.LastIndex(port, ":"); i >= 0 {
				port = port[i+1:]
			}
			return port
		}
	}
	return ""
}

type source struct {
	name   string
	client *http.Client
}

func sources(timeout time.Duration) []source {
	if c, name := chosenRelay(timeout); c != nil {
		return []source{{name: "tunnel " + name, client: c}}
	}
	out := []source{{name: "direct", client: &http.Client{Timeout: timeout}}}
	if relay := relayHTTPClient(timeout); relay != nil {
		out = append(out, source{name: "tunnel relay", client: relay})
	}
	return out
}

var relayChoice struct {
	name    string
	timeout time.Duration
}

func UseRelay(name string) { relayChoice.name = name }

func RelayChosen() bool { return relayChoice.name != "" }

func chosenRelay(timeout time.Duration) (*http.Client, string) {
	if relayChoice.name == "" {
		return nil, ""
	}
	c, err := RelayClientVia(relayChoice.name, timeout)
	if err != nil {
		return nil, ""
	}
	return c, relayChoice.name
}

var tagNameRe = regexp.MustCompile(`"tag_name"\s*:\s*"([^"]+)"`)
var versionValidRe = regexp.MustCompile(`^v?[0-9]+(\.[0-9]+){0,3}$`)

func latestTag() (string, error) {
	var lastErr error = fmt.Errorf("no source reachable")
	beta := Channel() == ChannelBeta

	apiURL := fmt.Sprintf("https://api.github.com/repos/%s/%s/releases/latest", app.RepoOwner, app.RepoName)
	if beta {
		apiURL = fmt.Sprintf("https://api.github.com/repos/%s/%s/releases?per_page=20", app.RepoOwner, app.RepoName)
	}
	rawURL := fmt.Sprintf("https://raw.githubusercontent.com/%s/%s/main/VERSION", app.RepoOwner, app.RepoName)

	for _, s := range sources(20 * time.Second) {
		resp, err := s.client.Get(apiURL)
		if err != nil {
			lastErr = err
			continue
		}
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 256*1024))
		resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			if tag := pickTag(string(body), beta); tag != "" {
				return tag, nil
			}
		}
		lastErr = fmt.Errorf("api via %s: status %d", s.name, resp.StatusCode)
	}

	for _, s := range sources(20 * time.Second) {
		resp, err := s.client.Get(rawURL)
		if err != nil {
			lastErr = err
			continue
		}
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 64))
		resp.Body.Close()
		if resp.StatusCode == http.StatusOK {
			if v := strings.TrimSpace(string(body)); versionValidRe.MatchString(v) && !beta {
				return v, nil
			}
		}
		lastErr = fmt.Errorf("VERSION via %s: status %d", s.name, resp.StatusCode)
	}
	return "", fmt.Errorf("could not reach GitHub (direct or through the tunnel relay): %v", lastErr)
}

func normVersion(v string) string { return strings.TrimPrefix(strings.TrimSpace(v), "v") }

const verParts = 4

func parseVer(v string) [verParts]int {
	var out [verParts]int
	for i, part := range strings.SplitN(normVersion(v), ".", verParts) {
		j := 0
		for j < len(part) && part[j] >= '0' && part[j] <= '9' {
			j++
		}
		out[i], _ = strconv.Atoi(part[:j])
	}
	return out
}

func newerVersion(remote, local string) bool {
	r, l := parseVer(remote), parseVer(local)
	for i := 0; i < verParts; i++ {
		if r[i] != l[i] {
			return r[i] > l[i]
		}
	}
	return false
}

func CheckUpdate() (bool, string, error) {
	tag, err := latestTag()
	if err != nil {
		return false, "", err
	}
	if !newerVersion(tag, app.Version) {
		if tag != "" && tag != app.Version {
			return false, fmt.Sprintf("Already up to date — %s is newer than the latest release (%s).",
				app.Version, tag), nil
		}
		return false, fmt.Sprintf("Already up to date (%s).", app.Version), nil
	}
	return true, fmt.Sprintf("Version %s is available (current %s).", tag, app.Version), nil
}

func pickTag(body string, beta bool) string {
	matches := tagNameRe.FindAllStringSubmatch(body, -1)
	if len(matches) == 0 {
		return ""
	}
	if !beta {
		tag := strings.TrimSpace(matches[0][1])
		if isPrerelease(tag) {
			return ""
		}
		return tag
	}

	best := ""
	for _, m := range matches {
		tag := strings.TrimSpace(m[1])
		if tag == "" {
			continue
		}
		if best == "" || newerVersion(tag, best) {
			best = tag
		}
	}
	return best
}

func downloadAsset(tag, destDir string, logf func(string)) (string, error) {
	asset := fmt.Sprintf("parstanel_linux_%s.tar.gz", runtime.GOARCH)
	url := fmt.Sprintf("%s/releases/download/%s/%s", repoURL(), tag, asset)

	if err := os.MkdirAll(destDir, 0755); err != nil {
		return "", err
	}
	dest := filepath.Join(destDir, asset)

	var lastErr error = fmt.Errorf("no source reachable")
	for _, s := range sources(3 * time.Minute) {
		logf("Downloading " + asset + " via " + s.name + "...")
		resp, err := s.client.Get(url)
		if err != nil {
			lastErr = err
			continue
		}
		if resp.StatusCode != http.StatusOK {
			resp.Body.Close()
			lastErr = fmt.Errorf("%s returned status %d", s.name, resp.StatusCode)
			continue
		}
		f, err := os.OpenFile(dest, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0644)
		if err != nil {
			resp.Body.Close()
			return "", err
		}
		_, err = io.Copy(f, resp.Body)
		resp.Body.Close()
		f.Close()
		if err != nil {
			lastErr = err
			continue
		}
		return dest, nil
	}
	return "", fmt.Errorf("could not download %s: %v", asset, lastErr)
}

func extractBinaryTo(archive, dest string) error {
	f, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return fmt.Errorf("not a valid release archive: %w", err)
	}
	defer gz.Close()

	tr := tar.NewReader(gz)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		if hdr.Typeflag != tar.TypeReg || filepath.Base(hdr.Name) != "parstanel" {
			continue
		}
		out, err := os.OpenFile(dest, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0755)
		if err != nil {
			return err
		}
		if _, err := io.Copy(out, tr); err != nil {
			out.Close()
			return err
		}
		return out.Close()
	}
	return fmt.Errorf("no `parstanel` binary found inside the archive")
}

func fetchChecksums(tag, asset string) (string, error) {
	url := fmt.Sprintf("%s/releases/download/%s/SHA256SUMS", repoURL(), tag)

	var lastErr error = fmt.Errorf("no source reachable")
	for _, s := range sources(30 * time.Second) {
		resp, err := s.client.Get(url)
		if err != nil {
			lastErr = err
			continue
		}
		if resp.StatusCode == http.StatusNotFound {
			resp.Body.Close()
			return "", nil
		}
		if resp.StatusCode != http.StatusOK {
			resp.Body.Close()
			lastErr = fmt.Errorf("%s returned status %d", s.name, resp.StatusCode)
			continue
		}
		body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
		resp.Body.Close()
		if err != nil {
			lastErr = err
			continue
		}
		return hashFor(string(body), asset), nil
	}
	return "", lastErr
}

func hashFor(sums, asset string) string {
	for _, line := range strings.Split(sums, "\n") {
		fields := strings.Fields(line)
		if len(fields) != 2 {
			continue
		}
		if strings.TrimPrefix(fields[1], "*") == asset {
			return strings.ToLower(fields[0])
		}
	}
	return ""
}

func verifyChecksum(path, want string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()

	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return err
	}
	got := hex.EncodeToString(h.Sum(nil))
	if !strings.EqualFold(got, want) {
		return fmt.Errorf("checksum mismatch — expected %s, got %s", want, got)
	}
	return nil
}

func extractBinary(archive string) error {
	tmp := app.BinPath + ".new"
	if err := extractBinaryTo(archive, tmp); err != nil {
		os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, app.BinPath)
}

func ApplyUpdate(logf func(string)) error {
	if logf == nil {
		logf = func(string) {}
	}
	tag, err := latestTag()
	if err != nil {
		return err
	}
	if !newerVersion(tag, app.Version) {
		logf("Already up to date (" + app.Version + ").")
		return nil
	}

	archive, err := downloadAsset(tag, app.InstallDir, logf)
	if err != nil {
		return err
	}

	want, cerr := fetchChecksums(tag, filepath.Base(archive))
	if cerr != nil {
		os.Remove(archive)
		return fmt.Errorf("could not fetch the checksum list for %s: %w\nInstall offline instead — see the README", tag, cerr)
	}
	if want == "" {
		os.Remove(archive)
		return fmt.Errorf("release %s publishes no checksum for %s\nInstall offline instead — see the README", tag, filepath.Base(archive))
	}
	if verr := verifyChecksum(archive, want); verr != nil {
		os.Remove(archive)
		return fmt.Errorf("the downloaded release failed verification: %w", verr)
	}
	logf("Checksum verified.")

	logf("Taking a safety snapshot...")
	snap, err := TakeSnapshot("pre-update")
	if err != nil {
		return fmt.Errorf("could not take a safety snapshot: %w", err)
	}
	logf("Snapshot saved: " + filepath.Base(snap.Dir))

	logf("Installing " + tag + "...")
	if err := extractBinary(archive); err != nil {
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
		return fmt.Errorf("update to %s failed health check (%s) — rolled back to %s",
			tag, strings.Join(bad, ", "), snap.Meta.Version)
	}

	logf("Health check passed.")
	logf("Update complete — now running " + tag + ".")
	return nil
}

func unhealthyAfterUpdate() []string {
	var bad []string
	if fileExists(app.ServiceDir+"/"+app.MonitorService) &&
		!WaitServiceActive(app.MonitorService, 20*time.Second) {
		bad = append(bad, "monitor")
	}
	for _, t := range List() {
		if !fileExists(app.ServiceDir + "/" + t.Service) {
			continue
		}
		if !WaitServiceActive(t.Service, 20*time.Second) {
			bad = append(bad, t.Name)
		}
	}
	return bad
}

func RollbackUpdate(s Snapshot, logf func(string)) error {
	return RestoreSnapshot(s, logf)
}