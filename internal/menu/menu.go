package menu

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/localproxy"
	"github.com/hasan714222-debug/ParsTanel/internal/manage"
	"github.com/hasan714222-debug/ParsTanel/internal/optimize"
	"github.com/hasan714222-debug/ParsTanel/internal/schedule"
	"github.com/hasan714222-debug/ParsTanel/internal/tui"
)

var ipStore atomic.Value

func Run() {
	requireRoot()

	manage.EnsureUnits()

	if err := manage.EnsureMonitorService(); err != nil {
		tui.Warn("Monitor service could not start: " + err.Error())
		tui.PressEnter()
	}

	go resolveServerIP()
	go manage.RefreshUpdateCheckIfStale(6 * time.Hour)

	for {
		tui.Clear()
		tui.Logo(app.Version)
		printUpdateBanner()
		tui.Rule()
		printMenu()

		switch strings.TrimSpace(tui.Prompt("Select an option: ")) {
		case "1":
			manage.SetupIran()
		case "2":
			manage.SetupKharej()
		case "3":
			manageMenu()
		case "4":
			backupMenu()
		case "5":
			optimizeMenu()
		case "6", "8":
			updateMenu()
		case "7", "9":
			uninstallMenu()
		case "0", "10", "exit", "q":
			tui.Clear()
			tui.Info("Goodbye!")
			return
		default:
			tui.Error("Invalid option.")
			tui.PressEnter()
		}
	}
}

func printUpdateBanner() {
	tag, ok := manage.UpdateAvailable()
	if !ok {
		return
	}
	fmt.Printf("  %s⬆ %s is available%s %s— choose option 6 to update safely%s\n",
		tui.Bold+tui.Red, tag, tui.Reset, tui.Gray, tui.Reset)
}

func printMenu() {
	fmt.Println()
	menuItem(1, "Setup Iran", "the server your users connect to — it exposes the ports")
	menuItem(2, "Setup Kharej", "the server abroad — it holds the real service")
	menuItem(3, "Manage", "tunnels, ports, transport, status, health check")
	menuItem(4, "Backup & Restore", "save or restore the full configuration")
	menuItem(5, "Optimize", "kernel & network tuning — BBR, buffers, limits")
	updateDesc := "safe update with automatic rollback"
	if tag, ok := manage.UpdateAvailable(); ok {
		updateDesc = tag + " is out — safe update with automatic rollback"
	}
	menuItem(6, "Update", updateDesc)
	menuItem(7, "Uninstall", "remove everything completely")
	fmt.Printf("\n  %s 0)%s %-18s  %s%s%s\n\n", tui.Red, tui.Reset, "Exit", tui.Gray, "close this menu", tui.Reset)
}

func menuItem(n int, title, desc string) {
	num := tui.Color(tui.Red, fmt.Sprintf("%2d)", n))
	if desc == "" {
		fmt.Printf("  %s %s%-18s%s\n", num, BoldWhite(), title, tui.Reset)
		return
	}
	fmt.Printf("  %s %s%-18s%s %s%s%s\n",
		num, BoldWhite(), title, tui.Reset, tui.Gray, desc, tui.Reset)
}

func BoldWhite() string {
	return tui.Bold + tui.White
}

func resolveServerIP() string {
	if v, _ := ipStore.Load().(string); v != "" {
		return v
	}
	ip := manage.PublicIPv4()
	if ip != "" && ip != "-" {
		ipStore.Store(ip)
		return ip
	}
	return "-"
}

func refreshLabel() string {
	h := schedule.AutoRefreshHours()
	if h <= 0 {
		return "disabled"
	}
	return fmt.Sprintf("every %dh", h)
}

func manageMenu() {
	for {
		tui.Clear()
		idx := tui.ChooseOpt("Manage", []tui.Option{
			{Title: "Manage Tunnels", Desc: "edit ports & transport, start/stop, live log, delete"},
			{Title: "Status", Desc: "live tunnel table"},
			{Title: "Health Check", Desc: "find problems and get a fix for each one"},
			{Title: "Link Test", Desc: "measure the link and get a transport recommendation"},
			{Title: "Speed Test", Desc: "measure what a tunnel actually carries, end to end"},
			{Title: "Game Latency Test", Desc: "estimate in-game ping to popular game servers through this exit"},
			{Title: "Exit Health", Desc: "score & rank every server address, pin the healthiest (multi-exit failover)"},
			{Title: "IP Spoofing Tester", Desc: "find which forged source IPs cross the firewall (for spoof carrier)"},
			{Title: "Tunnel Metrics", Desc: "traffic, packet loss and error correction per tunnel"},
			{Title: "Restart ALL", Desc: "restart every tunnel at once"},
			{Title: "Auto Refresh", Desc: "restart all tunnels every N hours — " + refreshLabel()},
			{Title: "Built-in Proxy", Desc: "be your own SOCKS5/HTTP backend — " + proxyLabel()},
			{Title: "File Locations", Desc: "where configs, logs and backups live"},
		})
		switch idx {
		case 0:
			manage.ManageTunnels()
		case 1:
			manage.StatusLive()
		case 2:
			manage.HealthCheck()
		case 3:
			manage.LinkTest()
		case 4:
			manage.SpeedTest()
		case 5:
			manage.GameLatencyTest()
		case 6:
			manage.ExitHealth()
		case 7:
			manage.SpoofTest()
		case 8:
			manage.TunnelMetrics()
		case 9:
			ok, failed := manage.RestartAll()
			tui.Success(fmt.Sprintf("Restarted %d tunnels (%d failed).", ok, failed))
			tui.PressEnter()
		case 10:
			autoRefreshMenu()
		case 11:
			builtinProxyMenu()
		case 12:
			manage.FileLocations()
		default:
			return
		}
	}
}

func proxyLabel() string {
	c := localproxy.Load()
	if !c.Enabled || !manage.ProxyRunning() {
		return "off"
	}
	return fmt.Sprintf("%s on :%d", c.Type, c.Port)
}

func builtinProxyMenu() {
	for {
		tui.Clear()
		tui.Title("Built-in Proxy")
		tui.Warn("This node serves its own SOCKS5 or HTTP proxy on a loopback port.")
		tui.Warn("Point a forwarded port at 127.0.0.1:<that port> and the tunnel exit")
		tui.Warn("is the proxy itself — no separate backend to install or keep running.")
		fmt.Println()

		c := localproxy.Load()
		if c.Enabled && manage.ProxyRunning() {
			tui.Success(fmt.Sprintf("Currently: %s proxy on 127.0.0.1:%d (running)", c.Type, c.Port))
		} else {
			tui.Info("Currently: off")
		}
		fmt.Println()

		idx := tui.ChooseOpt("Choose:", []tui.Option{
			{Title: "Enable / reconfigure", Desc: "pick SOCKS5 or HTTP, a port, and optional auth"},
			{Title: "Disable", Desc: "stop and remove the proxy service"},
			{Title: "Restart", Desc: "restart the proxy service"},
		})
		switch idx {
		case 0:
			configureProxy(c)
		case 1:
			if err := manage.DisableProxyService(); err != nil {
				tui.Error("Could not disable: " + err.Error())
			} else {
				tui.Success("Built-in proxy disabled.")
			}
			tui.PressEnter()
		case 2:
			if err := manage.EnableProxyService(c); err != nil {
				tui.Error("Failed to restart: " + err.Error())
			} else {
				tui.Success("Proxy service restarted.")
			}
			tui.PressEnter()
		default:
			return
		}
	}
}

func configureProxy(c localproxy.Config) {
	fmt.Println()
	kind := tui.ChooseOpt("Proxy type:", []tui.Option{
		{Title: "SOCKS5", Desc: "works for most apps; carries UDP too"},
		{Title: "HTTP", Desc: "for clients that only take an HTTP proxy (browsers)"},
	})
	switch kind {
	case 0:
		c.Type = localproxy.SOCKS5
	case 1:
		c.Type = localproxy.HTTP
	default:
		return
	}

	portDef := 10808
	if c.Port > 0 {
		portDef = c.Port
	}
	c.Port = tui.PromptInt("Port to listen on (loopback)", portDef)
	if c.Port <= 0 || c.Port > 65535 {
		tui.Error("Port must be between 1 and 65535.")
		tui.PressEnter()
		return
	}

	if tui.Confirm("Require a username/password", c.Username != "") {
		c.Username = tui.PromptDefault("Username", c.Username)
		c.Password = tui.PromptDefault("Password", c.Password)
	} else {
		c.Username, c.Password = "", ""
		tui.Warn("No auth — safe here: the proxy binds loopback and is only")
		tui.Warn("reachable through the token-authenticated tunnel.")
	}

	if err := manage.EnableProxyService(c); err != nil {
		tui.Error("Could not enable: " + err.Error())
	} else {
		tui.Success(fmt.Sprintf("%s proxy running on 127.0.0.1:%d.", c.Type, c.Port))
		tui.Info(fmt.Sprintf("Now forward a tunnel port to 127.0.0.1:%d (e.g. 443=127.0.0.1:%d).", c.Port, c.Port))
	}
	tui.PressEnter()
}

func backupMenu() {
	for {
		tui.Clear()
		tui.Title("Backup & Restore")
		fmt.Println()
		tui.Warn("A backup bundles every tunnel, tokens, TLS certs and the")
		tui.Warn("auto-refresh schedule into one portable .tar.gz archive.")
		tui.Warn("Backups live in " + app.BackupDir)
		fmt.Println()

		idx := tui.ChooseOpt("Choose:", []tui.Option{
			{Title: "Create a backup file", Desc: "saves into " + app.BackupDir},
			{Title: "Restore from a backup file", Desc: "pick one from the folder or enter a path"},
		})
		switch idx {
		case 0:
			createBackup()
		case 1:
			restoreBackup()
		default:
			return
		}
	}
}

func createBackup() {
	dir := tui.PromptDefault("Save the backup in which directory", app.BackupDir)
	path, err := manage.BackupToFile(dir)
	if err != nil {
		tui.Error("Backup failed: " + err.Error())
		tui.PressEnter()
		return
	}
	tui.Success("Backup created:")
	tui.Info("  " + path)
	fmt.Println()
	tui.Warn("Keep it private — it contains tunnel tokens and keys.")
	tui.PressEnter()
}

func restoreBackup() {
	archives, _ := filepath.Glob(app.BackupDir + "/*.tar.gz")

	var path string
	if len(archives) > 0 {
		opts := make([]tui.Option, 0, len(archives)+1)
		for _, a := range archives {
			opts = append(opts, tui.Option{Title: filepath.Base(a), Desc: "in " + app.BackupDir})
		}
		opts = append(opts, tui.Option{Title: "Enter a custom path", Desc: "an archive somewhere else"})
		fmt.Println()
		idx := tui.ChooseOpt("Restore which backup:", opts)
		switch {
		case idx < 0:
			return
		case idx < len(archives):
			path = archives[idx]
		default:
			path = tui.Prompt("Path to the backup .tar.gz file: ")
		}
	} else {
		tui.Warn("No backups found in " + app.BackupDir + " — enter a path manually.")
		path = tui.Prompt("Path to the backup .tar.gz file: ")
	}
	if path == "" {
		return
	}

	f, err := os.Open(path)
	if err != nil {
		tui.Error("Cannot open file: " + err.Error())
		tui.PressEnter()
		return
	}
	defer f.Close()

	tui.Warn("This overwrites existing tunnels/settings with the backup's contents.")
	if !tui.Confirm("Restore now", false) {
		return
	}

	res, err := manage.Restore(f)
	if err != nil {
		tui.Error("Restore failed: " + err.Error())
		tui.PressEnter()
		return
	}

	tui.Success(fmt.Sprintf("Restored %d file(s).", res.Files))
	if len(res.Tunnels) > 0 {
		tui.Info(fmt.Sprintf("Tunnels: %d re-registered, %d started, %d failed.",
			len(res.Tunnels), res.Started, res.Failed))
	}
	if res.AutoRefreshHours > 0 {
		tui.Info(fmt.Sprintf("Auto-refresh restored: every %d hour(s).", res.AutoRefreshHours))
	}
	tui.PressEnter()
}

func autoRefreshMenu() {
	tui.Clear()
	tui.Title("Auto Refresh Schedule")
	fmt.Println()
	tui.Info(fmt.Sprintf("Current interval: %s", refreshLabel()))
	fmt.Println()
	hours := tui.PromptInt("Auto refresh interval in hours (0 to disable)", schedule.AutoRefreshHours())
	if err := schedule.SetAutoRefresh(hours); err != nil {
		tui.Error("Failed to update schedule: " + err.Error())
	} else if hours <= 0 {
		tui.Success("Auto refresh disabled.")
	} else {
		tui.Success(fmt.Sprintf("All tunnels will restart every %d hour(s).", hours))
	}
	tui.PressEnter()
}

func optimizeMenu() {
	tui.Clear()
	tui.Title("Optimize — kernel & network tuning (BBR, buffers, limits)")
	fmt.Println()
	if !tui.Confirm("Apply system-wide network optimizations now", true) {
		return
	}
	fmt.Println()
	optimize.Apply(func(line string) { tui.Info("• " + line) })
	fmt.Println()
	tui.Success("Optimizations applied and saved to /etc/sysctl.d/99-parstanel.conf.")
	tui.Warn("A reboot is recommended for file-limit changes to fully apply.")
	tui.PressEnter()
}

func updateMenu() {
	for {
		tui.Clear()
		tui.Title("Update ParsTanel")
		tui.Warn("Current version: " + app.Version)
		tui.Warn("Release channel : " + manage.ChannelLabel())
		fmt.Println()

		idx := tui.ChooseOpt("Choose:", []tui.Option{
			{Title: "Check for updates", Desc: "install the latest release — safely, with automatic rollback"},
			{Title: "Install from a downloaded file", Desc: localUpdateDesc()},
			{Title: "Restore points", Desc: "go back to a previous version if something went wrong"},
			{Title: "Release channel", Desc: "stable releases only, or also test pre-releases"},
		})
		switch idx {
		case 0:
			runUpdate()
		case 1:
			runLocalUpdate()
		case 2:
			restorePointMenu()
		case 3:
			channelMenu()
		default:
			return
		}
	}
}

func localUpdateDesc() string {
	if u, ok := manage.FindLocalUpdate(); ok {
		if u.Version != "" {
			return "found " + u.Version + " in " + filepath.Dir(u.Path)
		}
		return "found " + filepath.Base(u.Path) + " in " + filepath.Dir(u.Path)
	}
	return "put " + manage.LocalAssetName() + " in /root first"
}

func runLocalUpdate() {
	tui.Clear()
	tui.Title("Install from a downloaded file")
	fmt.Println()

	u, ok := manage.FindLocalUpdate()
	if !ok {
		tui.Error("No " + manage.LocalAssetName() + " found.")
		fmt.Println()
		tui.Info("Download it from the releases page on any machine that can reach")
		tui.Info("GitHub, copy it to this server, and choose this again:")
		fmt.Println()
		fmt.Printf("  %sscp %s root@this-server:/root/%s\n\n", tui.Gray, manage.LocalAssetName(), tui.Reset)
		tui.Info("Looked in: " + strings.Join(manage.LocalUpdateSearchedIn(), ", "))
		tui.Info("The name has to be exactly that — it says which architecture the")
		tui.Info("binary inside is built for, and this server runs " + runtime.GOARCH + ".")
		tui.PressEnter()
		return
	}

	fmt.Printf("  %sFile%s     %s\n", tui.Gray, tui.Reset, u.Path)
	fmt.Printf("  %sSize%s     %.1f MB\n", tui.Gray, tui.Reset, float64(u.Size)/(1<<20))
	fmt.Printf("  %sAdded%s    %s\n", tui.Gray, tui.Reset, u.When.Format("2006-01-02 15:04"))
	if u.Version != "" {
		fmt.Printf("  %sVersion%s  %s%s%s  (this server runs %s)\n",
			tui.Gray, tui.Reset, BoldWhite(), u.Version, tui.Reset, app.Version)
	} else {
		fmt.Printf("  %sVersion%s  %sunknown — the binary inside did not answer%s\n",
			tui.Gray, tui.Reset, tui.Gray, tui.Reset)
	}
	if u.Checksums != "" {
		fmt.Printf("  %sChecksum%s %s\n", tui.Gray, tui.Reset, u.Checksums)
	} else {
		fmt.Printf("  %sChecksum%s %sno SHA256SUMS beside it — it will be installed unverified%s\n",
			tui.Gray, tui.Reset, tui.Gray, tui.Reset)
	}
	fmt.Println()

	if u.Version != "" && u.Version == app.Version {
		tui.Warn("That is the version already running. Installing it again is fine.")
	}

	tui.Info("A restore point is taken first. If a tunnel does not come back, the")
	tui.Info("update rolls itself back on its own.")
	fmt.Println()
	if !tui.Confirm("Install it?", true) {
		return
	}

	fmt.Println()
	if err := manage.ApplyLocalUpdate(u, func(l string) { tui.Info("• " + l) }); err != nil {
		tui.Error(err.Error())
		tui.PressEnter()
	} else {
		tui.Success("Updated successfully. Reopening...")
		time.Sleep(1500 * time.Millisecond)
		reexecSelf()
	}
}

func channelMenu() {
	tui.Clear()
	tui.Title("Release channel")
	fmt.Println()
	tui.Info("Current: " + manage.ChannelLabel())
	fmt.Println()
	tui.Warn("Stable installs finished releases only. Beta also installs")
	tui.Warn("pre-releases, so you can try a new version on one server before")
	tui.Warn("it reaches everyone.")
	fmt.Println()

	opts, values := manage.ChannelOptions()
	idx := tui.ChooseOpt("Choose a channel:", opts)
	if idx < 0 {
		return
	}
	if err := manage.SetChannel(values[idx]); err != nil {
		tui.Error("Could not save the channel: " + err.Error())
	} else {
		tui.Success("Release channel set to " + manage.ChannelLabel() + ".")
	}
	tui.PressEnter()
}

func runUpdate() {
	tui.Clear()
	tui.Title("Check for updates")
	fmt.Println()
	tui.Info("Checking GitHub releases (direct, then through the tunnel relay)...")

	available, summary, err := manage.CheckUpdate()
	if err != nil {
		if !offerRelay(err) {
			return
		}
		available, summary, err = manage.CheckUpdate()
		if err != nil {
			tui.Error(err.Error())
			tui.PressEnter()
			return
		}
	}
	if !available {
		tui.Success(summary)
		tui.PressEnter()
		return
	}

	tui.Warn(summary)
	fmt.Println()
	tui.Info("A restore point is saved first. If anything fails to come back up,")
	tui.Info("ParsTanel puts the previous version back automatically.")
	fmt.Println()
	if !tui.Confirm("Download and install the update now", true) {
		return
	}
	fmt.Println()
	err = manage.ApplyUpdate(func(l string) { tui.Info("• " + l) })
	if err != nil && !manage.RelayChosen() {
		fmt.Println()
		if offerRelay(err) {
			err = manage.ApplyUpdate(func(l string) { tui.Info("• " + l) })
		}
	}
	if err != nil {
		tui.Error("Update failed: " + err.Error())
		tui.PressEnter()
	} else {
		tui.Success("ParsTanel updated successfully. Restarting...")
		time.Sleep(1500 * time.Millisecond)
		reexecSelf()
	}
}

func offerRelay(reason error) bool {
	options := manage.RelayOptions()
	if len(options) == 0 {
		tui.Error(reason.Error())
		fmt.Println()
		tui.Warn("No tunnel is online either, so there is no way out from here.")
		tui.Info("Install offline instead: download the release on a machine that can")
		tui.Info("reach GitHub and copy it across — see the README.")
		tui.PressEnter()
		return false
	}

	tui.Error(reason.Error())
	fmt.Println()
	tui.Info("This server cannot reach GitHub directly. One of its tunnels can:")
	tui.Info("the far end fetches the release and passes it back.")
	fmt.Println()

	opts := make([]tui.Option, len(options))
	for i, o := range options {
		desc := "restarts this tunnel briefly to open the relay port"
		if o.Ready {
			desc = "ready now — no restart needed"
		}
		opts[i] = tui.Option{Title: o.Name, Desc: desc}
	}
	idx := tui.ChooseOpt("Fetch the update through which tunnel?", opts)
	if idx < 0 || idx >= len(options) {
		return false
	}

	chosen := options[idx]
	if !chosen.Ready {
		fmt.Println()
		tui.Warn("Opening the relay port restarts " + chosen.Name + ". Traffic on it stops")
		tui.Warn("for a moment and comes back on its own.")
		if !tui.Confirm("Go ahead", true) {
			return false
		}
	}

	manage.UseRelay(chosen.Name)
	fmt.Println()
	tui.Info("Fetching through " + chosen.Name + "...")
	return true
}

func restorePointMenu() {
	snaps := manage.ListSnapshots()
	tui.Clear()
	tui.Title("Restore points")
	tui.Warn("Saved automatically before every update — binary plus all configs.")
	fmt.Println()

	if len(snaps) == 0 {
		tui.Info("No restore points yet — one is created the first time you update.")
		tui.PressEnter()
		return
	}

	opts := make([]tui.Option, len(snaps))
	for i, s := range snaps {
		desc := fmt.Sprintf("version %s", s.Meta.Version)
		if n := len(s.Meta.Tunnels); n > 0 {
			desc += fmt.Sprintf(" · %d tunnel(s)", n)
		}
		opts[i] = tui.Option{Title: s.Meta.Stamp, Desc: desc}
	}
	idx := tui.ChooseOpt("Roll back to which restore point:", opts)
	if idx < 0 {
		return
	}

	chosen := snaps[idx]
	fmt.Println()
	tui.Warn("This puts back the binary and ALL configs from " + chosen.Meta.Stamp + ",")
	tui.Warn("then restarts every tunnel.")
	if !tui.Confirm("Roll back now", false) {
		return
	}
	fmt.Println()
	if err := manage.RollbackUpdate(chosen, func(l string) { tui.Info("• " + l) }); err != nil {
		tui.Error("Rollback failed: " + err.Error())
		tui.PressEnter()
	} else {
		tui.Success("Rolled back to " + chosen.Meta.Version + " successfully. Restarting...")
		time.Sleep(1500 * time.Millisecond)
		reexecSelf()
	}
}

func reexecSelf() {
	cmd := exec.Command(app.BinPath)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	_ = cmd.Run()
	os.Exit(0)
}

func uninstallMenu() {
	tui.Clear()
	tui.Title("Uninstall ParsTanel")
	fmt.Println()
	tui.Error("WARNING: This will permanently remove:")
	tui.Warn("  • all tunnel services and configurations")
	tui.Warn("  • the monitor watchdog service")
	tui.Warn("  • the auto-refresh cron job")
	tui.Warn("  • the parstanel binary itself")
	fmt.Println()
	if !tui.Confirm("Are you absolutely sure", false) {
		return
	}

	repo := manage.InstallPath()
	if repo == "" {
		repo = app.InstallDir
	}

	for _, t := range manage.List() {
		_ = manage.Delete(t.Name)
	}
	_ = manage.DisableMonitorService()
	_ = schedule.SetAutoRefresh(0)
	os.RemoveAll(app.ConfigDir)
	if err := os.Remove(app.BinPath); err != nil {
		tui.Warn("Could not remove binary at " + app.BinPath + " — remove it manually.")
	}
	if repo != "" && repo != "/" && repo != os.Getenv("HOME") {
		if err := os.RemoveAll(repo); err != nil {
			tui.Warn("Could not remove folder " + repo + " — remove it manually.")
		} else {
			tui.Info("Removed folder: " + repo)
		}
	}
	tui.Success("ParsTanel has been completely uninstalled. Goodbye!")
	os.Exit(0)
}

func requireRoot() {
	if os.Geteuid() != 0 {
		tui.Error("ParsTanel must be run as root (use: sudo parstanel).")
		os.Exit(1)
	}
}
