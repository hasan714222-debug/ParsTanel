BIN      := parstanel
BIN_PATH := /usr/local/bin/parstanel
LDFLAGS  := -s -w

.PHONY: all build install uninstall clean tidy run vendor release-linux release version

all: build

tidy:
	go mod tidy

# Sync the raw VERSION file with the app.Version constant, so they can never drift.
version:
	@grep -oE 'Version = "[^"]+"' internal/app/app.go | grep -oE 'v[0-9.]+' > VERSION
	@echo "VERSION -> $$(cat VERSION)"

build: tidy
	CGO_ENABLED=0 go build -trimpath -ldflags "$(LDFLAGS)" -o $(BIN) .

vendor:
	go mod tidy
	go mod vendor

# Cross-compile static Linux binaries (no libc / no Go needed to run).
release-linux:
	mkdir -p dist
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath -ldflags "$(LDFLAGS)" -o dist/parstanel-linux-amd64 .
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -trimpath -ldflags "$(LDFLAGS)" -o dist/parstanel-linux-arm64 .

# GitHub release assets: parstanel_linux_<arch>.tar.gz, each containing a single
# `parstanel` binary. These are what install.sh and the in-app updater download.
release: version release-linux
	mkdir -p release
	cp dist/parstanel-linux-amd64 dist/parstanel && tar -czf release/parstanel_linux_amd64.tar.gz -C dist parstanel && rm dist/parstanel
	cp dist/parstanel-linux-arm64 dist/parstanel && tar -czf release/parstanel_linux_arm64.tar.gz -C dist parstanel && rm dist/parstanel
	cd release && (sha256sum parstanel_linux_*.tar.gz > SHA256SUMS 2>/dev/null || shasum -a 256 parstanel_linux_*.tar.gz > SHA256SUMS)
	@echo "Release assets ready in ./release"
	@cat release/SHA256SUMS

install: build
	install -m 0755 $(BIN) $(BIN_PATH)
	mkdir -p /etc/parstanel
	@echo "Installed. Run: parstanel"

uninstall:
	rm -f $(BIN_PATH)

run: build
	sudo ./$(BIN)

clean:
	rm -f $(BIN)
	rm -rf dist release