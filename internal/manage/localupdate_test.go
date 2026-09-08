package manage

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func withLocalDirs(t *testing.T, dirs ...string) {
	t.Helper()
	old := localUpdateDirsFn
	localUpdateDirsFn = func() []string { return dirs }
	t.Cleanup(func() { localUpdateDirsFn = old })
}

func TestOnlyThisMachinesArchiveIsOffered(t *testing.T) {
	dir := t.TempDir()
	withLocalDirs(t, dir)

	if _, ok := FindLocalUpdate(); ok {
		t.Fatal("found an update in an empty directory")
	}

	other := "arm64"
	if runtime.GOARCH == "arm64" {
		other = "amd64"
	}
	for _, name := range []string{
		"parstanel.tar.gz",
		"parstanel_linux_" + other + ".tar.gz",
		"parstanel_linux_" + runtime.GOARCH + ".tgz",
		"ParsTanel_linux_" + runtime.GOARCH + ".tar.gz",
	} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0644); err != nil {
			t.Fatal(err)
		}
	}
	if u, ok := FindLocalUpdate(); ok {
		t.Errorf("offered %s — an archive for another architecture produces a binary that will not execute", u.Path)
	}

	want := filepath.Join(dir, LocalAssetName())
	if err := os.WriteFile(want, []byte("not really an archive"), 0644); err != nil {
		t.Fatal(err)
	}
	u, ok := FindLocalUpdate()
	if !ok {
		t.Fatal("did not find the release archive for this machine")
	}
	if u.Path != want {
		t.Errorf("found %s, want %s", u.Path, want)
	}
	if u.Version != "" {
		t.Errorf("claimed version %q for a file that is not a release", u.Version)
	}
}

func TestAnEmptyFileIsNotOffered(t *testing.T) {
	dir := t.TempDir()
	withLocalDirs(t, dir)
	if err := os.WriteFile(filepath.Join(dir, LocalAssetName()), nil, 0644); err != nil {
		t.Fatal(err)
	}
	if _, ok := FindLocalUpdate(); ok {
		t.Error("a zero-byte file was offered as an update")
	}
}

func TestTheChecksumListBesideItIsUsed(t *testing.T) {
	dir := t.TempDir()
	withLocalDirs(t, dir)

	archive := filepath.Join(dir, LocalAssetName())
	if err := os.WriteFile(archive, []byte("pretend release"), 0644); err != nil {
		t.Fatal(err)
	}
	sums := filepath.Join(dir, "SHA256SUMS")
	if err := os.WriteFile(sums, []byte("0000  "+LocalAssetName()+"\n"), 0644); err != nil {
		t.Fatal(err)
	}

	u, ok := FindLocalUpdate()
	if !ok {
		t.Fatal("did not find the archive")
	}
	if u.Checksums != sums {
		t.Fatalf("checksum list = %q, want %q", u.Checksums, sums)
	}

	err := ApplyLocalUpdate(u, nil)
	if err == nil {
		t.Fatal("installed an archive whose checksum did not match")
	}
	if !strings.Contains(err.Error(), "does not match") {
		t.Errorf("refused for the wrong reason: %v", err)
	}
	if _, serr := os.Stat(archive); serr != nil {
		t.Error("the archive was deleted after a failed verification")
	}
}

func TestAChecksumListThatDoesNotNameTheArchiveIsRefused(t *testing.T) {
	dir := t.TempDir()
	withLocalDirs(t, dir)

	if err := os.WriteFile(filepath.Join(dir, LocalAssetName()), []byte("x"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "SHA256SUMS"),
		[]byte("0000  something_else.tar.gz\n"), 0644); err != nil {
		t.Fatal(err)
	}
	u, _ := FindLocalUpdate()
	err := ApplyLocalUpdate(u, nil)
	if err == nil || !strings.Contains(err.Error(), "says nothing about") {
		t.Errorf("a mismatched checksum list was not reported: %v", err)
	}
}

func TestAChecksumListCoveringAnotherArchiveIsKept(t *testing.T) {
	dir := t.TempDir()
	other := "parstanel_linux_arm64.tar.gz"
	if runtime.GOARCH == "arm64" {
		other = "parstanel_linux_amd64.tar.gz"
	}
	if err := os.WriteFile(filepath.Join(dir, other), []byte("x"), 0644); err != nil {
		t.Fatal(err)
	}
	sums := filepath.Join(dir, "SHA256SUMS")
	u := LocalUpdate{Path: filepath.Join(dir, LocalAssetName()), Checksums: sums}

	body := "aaa  " + LocalAssetName() + "\nbbb  " + other + "\n"
	if !namesAnotherFile(body, u) {
		t.Error("a checksum list covering the other architecture's archive would be removed")
	}

	os.Remove(filepath.Join(dir, other))
	if namesAnotherFile(body, u) {
		t.Error("a checksum list naming only files that are gone was kept")
	}
}

func TestTheOperatorIsToldWhereToPutTheFile(t *testing.T) {
	dirs := LocalUpdateSearchedIn()
	if len(dirs) == 0 {
		t.Fatal("nowhere is searched")
	}
	if dirs[0] != "/root" {
		t.Errorf("the first place searched is %q, want /root", dirs[0])
	}
	if !strings.HasPrefix(LocalAssetName(), "parstanel_linux_") ||
		!strings.HasSuffix(LocalAssetName(), ".tar.gz") {
		t.Errorf("the asset name %q is not what a release publishes", LocalAssetName())
	}
	if !strings.Contains(LocalAssetName(), runtime.GOARCH) {
		t.Errorf("the asset name %q does not name this machine's architecture", LocalAssetName())
	}
}