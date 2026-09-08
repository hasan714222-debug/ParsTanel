package transport

import (
	"errors"
	"fmt"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/metrics"
	"github.com/sirupsen/logrus"
)

type localDialReporter struct {
	mu   sync.Mutex
	last map[string]time.Time
}

const localDialQuiet = 30 * time.Second

var localDial = &localDialReporter{last: map[string]time.Time{}}

func (r *localDialReporter) Report(logger *logrus.Logger, addr string, err error) {
	metrics.ReportLocalDialFailure(addr, whyLocalDialFailed(err))

	r.mu.Lock()
	if t, seen := r.last[addr]; seen && time.Since(t) < localDialQuiet {
		r.mu.Unlock()
		return
	}
	r.last[addr] = time.Now()
	r.mu.Unlock()

	logger.Error(localDialMessage(addr, err))
}

func whyLocalDialFailed(err error) string {
	switch {
	case errors.Is(err, syscall.ECONNREFUSED):
		return "refused"
	case isTimeout(err):
		return "timeout"
	default:
		return "unreachable"
	}
}

func ReportLocalDialOK() { metrics.ReportLocalDialSuccess() }

func localDialMessage(addr string, err error) string {
	var b strings.Builder

	switch {
	case errors.Is(err, syscall.ECONNREFUSED):
		fmt.Fprintf(&b, "nothing is listening on %s on THIS server.\n", addr)
		b.WriteString("  The tunnel delivered the connection correctly — the problem is the\n")
		b.WriteString("  service being forwarded to. Either it is not running, or it is bound\n")
		b.WriteString("  to a different address (many panels bind a public IP, not 127.0.0.1).\n")
		fmt.Fprintf(&b, "  Check with:  ss -tlnp | grep %s", portOnly(addr))

	case isTimeout(err):
		fmt.Fprintf(&b, "timed out connecting to %s on THIS server.\n", addr)
		b.WriteString("  The tunnel delivered the connection correctly. Something is listening\n")
		b.WriteString("  but not answering — a firewall rule on this machine, or a service\n")
		b.WriteString("  that is up but wedged.\n")
		fmt.Fprintf(&b, "  Check with:  ss -tlnp | grep %s", portOnly(addr))

	default:
		fmt.Fprintf(&b, "could not reach %s on THIS server: %v\n", addr, err)
		b.WriteString("  The tunnel delivered the connection correctly — this is the last hop,\n")
		b.WriteString("  from this machine to the service it forwards to.")
	}

	b.WriteString("\n  (repeats are suppressed for 30s)")
	return b.String()
}

func isTimeout(err error) bool {
	var t interface{ Timeout() bool }
	return errors.As(err, &t) && t.Timeout()
}

func portOnly(addr string) string {
	if i := strings.LastIndex(addr, ":"); i >= 0 && i < len(addr)-1 {
		return addr[i+1:]
	}
	return addr
}