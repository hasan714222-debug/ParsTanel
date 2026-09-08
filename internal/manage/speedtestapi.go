package manage

import (
	"context"
	"errors"
	"fmt"
	"syscall"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
)

type SpeedTestTarget struct {
	Spec        string `json:"spec"`
	ListenPort  int    `json:"listenPort"`
	BackendPort int    `json:"backendPort"`
	Reason      string `json:"reason,omitempty"`
}

func (t SpeedTestTarget) Usable() bool { return t.Reason == "" }

type SpeedTestPlan struct {
	Kind    string            `json:"kind"`
	Peer    string            `json:"peer,omitempty"`
	Port    int               `json:"port,omitempty"`
	Targets []SpeedTestTarget `json:"targets,omitempty"`
	Blocked string            `json:"blocked,omitempty"`
	Seconds int               `json:"seconds"`
}

const speedTestBudget = 25 * time.Second

func SpeedTestPlanFor(name string) (SpeedTestPlan, error) {
	t, ok := Find(name)
	if !ok {
		return SpeedTestPlan{}, fmt.Errorf("no tunnel named %q", name)
	}
	plan := SpeedTestPlan{Seconds: int((throughputWarmup + throughputRun) / time.Second)}

	if !isForwardKind(t) {
		plan.Kind = "l3"
		plan.Peer, plan.Port = tunnelPeerIP(t.Name), throughputPort
		if plan.Peer == "" {
			plan.Blocked = "this tunnel has no peer address to measure against"
		}
		return plan, nil
	}

	plan.Kind = "forward"
	if !HoldsPorts(t) {
		plan.Blocked = "this side holds the backends, so it is the side that receives — " +
			"measure from the server that exposes the ports"
		return plan, nil
	}
	targets, err := forwardMappings(t)
	if err != nil {
		return SpeedTestPlan{}, err
	}
	for _, m := range targets {
		plan.Targets = append(plan.Targets, SpeedTestTarget{
			Spec: m.Spec, ListenPort: m.ListenPort, BackendPort: m.TargetPort, Reason: m.Reason,
		})
	}
	if len(plan.Targets) == 0 {
		plan.Blocked = "this tunnel forwards no ports, so there is nothing to measure through"
	}
	return plan, nil
}

func RunSpeedTest(ctx context.Context, name string, listenPort int) (ThroughputResult, error) {
	plan, err := SpeedTestPlanFor(name)
	if err != nil {
		return ThroughputResult{}, err
	}
	if plan.Blocked != "" {
		return ThroughputResult{}, fmt.Errorf("%s", plan.Blocked)
	}

	peer, port := plan.Peer, plan.Port
	if plan.Kind == "forward" {
		var chosen *SpeedTestTarget
		for i := range plan.Targets {
			if plan.Targets[i].ListenPort == listenPort {
				chosen = &plan.Targets[i]
				break
			}
		}
		if chosen == nil {
			return ThroughputResult{}, fmt.Errorf("port %d is not one of this tunnel's mappings", listenPort)
		}
		if !chosen.Usable() {
			return ThroughputResult{}, fmt.Errorf("that mapping cannot carry a measurement: %s", chosen.Reason)
		}
		peer, port = forwardBackendHost, chosen.ListenPort
	}

	ctx, cancel := context.WithTimeout(ctx, speedTestBudget)
	defer cancel()
	res, err := MeasureThroughputOn(ctx, peer, port)
	if err != nil && plan.Kind == "forward" && isRefused(err) {
		return res, refusedLocally(name, port)
	}
	return res, err
}

func isRefused(err error) bool {
	return errors.Is(err, syscall.ECONNREFUSED)
}

func refusedLocally(name string, port int) error {
	if !IsActive(app.ServiceName(name)) {
		return fmt.Errorf("this tunnel is not running on this server, so nothing is "+
			"listening on port %d — start it and measure again", port)
	}
	return fmt.Errorf("nothing is listening on port %d on this server even though %s is "+
		"running — check the tunnel's forwarded ports, and its log for a listener that "+
		"could not bind", port, name)
}
