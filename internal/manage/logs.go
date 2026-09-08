package manage

import (
	"os/exec"
	"strconv"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

func Logs(name string, n int) string {
	if n <= 0 {
		n = 100
	}
	return journalCache.get(name+"\x00"+strconv.Itoa(n), func() string {
		return readLogs(name, n)
	})
}

func readLogs(name string, n int) string {
	out, err := exec.Command("journalctl",
		"-u", app.ServiceName(name),
		"-n", strconv.Itoa(n),
		"--no-pager", "-o", "short-iso").CombinedOutput()
	if err != nil && len(out) == 0 {
		return "No logs available for " + name
	}
	return string(out)
}