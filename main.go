package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/hasan714222-debug/ParsTanel/cmd"
	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/localproxy"
	"github.com/hasan714222-debug/ParsTanel/internal/manage"
	"github.com/hasan714222-debug/ParsTanel/internal/menu"
	"github.com/hasan714222-debug/ParsTanel/internal/monitor"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
)

var logger = utils.NewLogger("info")

func main() {
	configPath := flag.String("c", "", "path to a tunnel configuration file (TOML) — runs in engine mode")
	showVersion := flag.Bool("v", false, "print the version and exit")
	restartAll := flag.Bool("restart-all", false, "restart every configured tunnel and exit (used by the auto-refresh job)")
	monitorMode := flag.Bool("monitor", false, "run the watchdog service (used by the parstanel-monitor service)")
	proxyMode := flag.Bool("proxy", false, "run the built-in SOCKS5/HTTP proxy (used by the parstanel-proxy service)")
	flag.Parse()

	switch {
	case *showVersion:
		fmt.Println(app.Version)
		return
	case *restartAll:
		ok, failed := manage.RestartAll()
		fmt.Printf("restarted %d tunnels, %d failed\n", ok, failed)
		return
	case *monitorMode:
		monitor.Run()
		return
	case *proxyMode:
		runProxy()
		return
	}

	// No config file -> interactive menu.
	if *configPath == "" {
		menu.Run()
		return
	}

	runEngine(*configPath)
}

func runProxy() {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go localproxy.Run(ctx)
	<-sigChan
	cancel()
	logger.Info("parstanel proxy stopped")
}

func runEngine(configPath string) {
	ctx, cancel := context.WithCancel(context.Background())

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)

	go cmd.Run(configPath, ctx)

	<-sigChan
	cancel()
	time.Sleep(1 * time.Second)
	logger.Info("parstanel engine stopped")
}