package cmd

import (
	"fmt"
	"os/exec"
	"runtime"
	"syscall"
)

// ApplyTCPTuning applies temporary TCP optimizations for Linux to handle massive connections
func ApplyTCPTuning() {
	if runtime.GOOS == "linux" {
		logger.Info("Applying TCP optimizations for Linux...")

		// Define the buffer sizes to try
		bufferSizes := []int{
			256 * 1024 * 1024, // 256MB
			128 * 1024 * 1024, // 128MB
			64 * 1024 * 1024,  // 64MB
			32 * 1024 * 1024,  // 32MB
			16 * 1024 * 1024,  // 16MB
		}

		// Loop through buffer sizes and attempt to apply them
		for _, size := range bufferSizes {
			cmd := []string{"sysctl", "-w", fmt.Sprintf("net.core.rmem_max=%d", size)}
			if err := exec.Command(cmd[0], cmd[1:]...).Run(); err == nil {
				logger.Printf("Successfully set rmem_max to %d\n", size)
				break
			} else {
				logger.Debugf("Failed to set rmem_max to %d, trying next lower value...\n", size)
			}
		}

		// Same for wmem_max
		for _, size := range bufferSizes {
			cmd := []string{"sysctl", "-w", fmt.Sprintf("net.core.wmem_max=%d", size)}
			if err := exec.Command(cmd[0], cmd[1:]...).Run(); err == nil {
				logger.Printf("Successfully set wmem_max to %d\n", size)
				break
			} else {
				logger.Debugf("Failed to set wmem_max to %d, trying next lower value...\n", size)
			}
		}

		// Commands for optimizing TCP parameters
		commands := [][]string{
			{"sysctl", "-w", "net.ipv4.ip_local_port_range=1024 65535"},
			{"sysctl", "-w", "net.ipv4.tcp_tw_reuse=1"},
			{"sysctl", "-w", "net.ipv4.tcp_fin_timeout=15"},
			{"sysctl", "-w", "net.core.somaxconn=65536"},
			{"sysctl", "-w", "net.ipv4.tcp_max_syn_backlog=20480"},
			{"sysctl", "-w", "net.ipv4.tcp_window_scaling=1"},
			{"sysctl", "-w", "net.ipv4.tcp_fastopen=3"},
			{"sysctl", "-w", "net.ipv4.tcp_notsent_lowat=32768"},
			{"sysctl", "-w", "net.core.rmem_default=1048576"},
			{"sysctl", "-w", "net.core.wmem_default=1048576"},
		}

		for _, cmd := range commands {
			err := exec.Command(cmd[0], cmd[1:]...).Run()
			if err != nil {
				logger.Errorf("Failed to apply TCP tuning: %s", cmd)
			} else {
				logger.Debugf("Successfully applied: %s", cmd)
			}
		}

		// Set file descriptor limit programmatically
		var rLimit syscall.Rlimit
		err := syscall.Getrlimit(syscall.RLIMIT_NOFILE, &rLimit)
		if err != nil {
			logger.Errorf("Error getting Rlimit: %v", err)
		} else {
			logger.Debugf("Current file descriptor limit: %d", rLimit.Cur)

			rLimit.Max = 1048576
			rLimit.Cur = 1048576
			err = syscall.Setrlimit(syscall.RLIMIT_NOFILE, &rLimit)
			if err != nil {
				logger.Warnf("could not raise the file descriptor limit (%v) — continuing on the current limit of %d", err, rLimit.Cur)
			} else {
				logger.Debugf("Successfully set file descriptor limit to: %d", rLimit.Cur)
			}
		}
	} else {
		logger.Info("Non-Linux system detected, skipping TCP optimizations.")
	}
}
