package monitor

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"sync"
	"syscall"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/manage"
	"github.com/hasan714222-debug/ParsTanel/internal/socks"
	"github.com/hasan714222-debug/ParsTanel/internal/tunhist"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/sirupsen/logrus"
)

func Run() {
	logger := utils.NewLogger("info")
	logger.Info("parstanel monitor started")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	startSocksRelays(ctx, logger)

	var wg sync.WaitGroup
	jobs := []struct {
		name string
		fn   func(context.Context)
	}{
		{"watchdog", manage.RunWatchdog},
		{"history sampler", tunhist.Run},
		{"auto-backup", manage.RunAutoBackup},
	}
	for _, job := range jobs {
		wg.Add(1)
		go func(name string, fn func(context.Context)) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					logger.Errorf("%s panicked and was stopped; the other monitor jobs keep running: %v", name, r)
				}
			}()
			fn(ctx)
			logger.Infof("%s stopped", name)
		}(job.name, job.fn)
	}

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	<-sig

	logger.Info("parstanel monitor stopping")
	cancel()
	wg.Wait()
}

func startSocksRelays(ctx context.Context, logger *logrus.Logger) {
	auth := func(_, pass string) bool { return manage.TokenMatches(pass) }

	tunnels := manage.List()
	ports := map[int]string{}

	if manage.LegacySocksInUse(tunnels) {
		ports[app.SocksInternalPort] = "legacy"
	}
	for _, t := range tunnels {
		if tok := manage.TunnelToken(t.Name); tok != "" {
			ports[app.SocksPortForToken(tok)] = t.Name
		}
	}

	for port, why := range ports {
		go func(port int, why string) {
			addr := fmt.Sprintf("127.0.0.1:%d", port)
			if err := socks.Serve(ctx, addr, auth); err != nil {
				logger.Warnf("SOCKS relay for %s could not listen on %s: %v", why, addr, err)
				return
			}
			logger.Infof("SOCKS relay for %s listening on %s", why, addr)
		}(port, why)
	}
}
