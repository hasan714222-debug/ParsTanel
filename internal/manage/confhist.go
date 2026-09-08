package manage

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/tui"
)

const (
	confHistKeep = 10
	confHistDir  = "history"
)

var confHistRoot = app.ConfigDir

type ConfigChange struct {
	At   time.Time `json:"at"`
	Note string    `json:"note,omitempty"`
	Prev string    `json:"prev"`
}

func confHistPath(name string) string {
	return filepath.Join(confHistRoot, confHistDir, name+".json")
}

func ConfigHistory(name string) []ConfigChange {
	b, err := os.ReadFile(confHistPath(name))
	if err != nil {
		return nil
	}
	var out []ConfigChange
	if err := json.Unmarshal(b, &out); err != nil {
		return nil
	}
	sort.Slice(out, func(i, j int) bool { return out[i].At.After(out[j].At) })
	return out
}

func recordConfigChange(name string, prev []byte, note string) {
	if len(prev) == 0 {
		return
	}
	dir := filepath.Join(confHistRoot, confHistDir)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return
	}

	entries := append([]ConfigChange{{At: time.Now(), Note: note, Prev: string(prev)}},
		ConfigHistory(name)...)
	if len(entries) > confHistKeep {
		entries = entries[:confHistKeep]
	}

	b, err := json.MarshalIndent(entries, "", "  ")
	if err != nil {
		return
	}
	_ = os.WriteFile(confHistPath(name), b, 0o600)
}

func ConfigChangeTimes(name string) []int64 {
	h := ConfigHistory(name)
	out := make([]int64, 0, len(h))
	for i := len(h) - 1; i >= 0; i-- {
		out = append(out, h[i].At.Unix())
	}
	return out
}

func RestoreConfigFrom(name string, at time.Time) error {
	for _, c := range ConfigHistory(name) {
		if !c.At.Equal(at) {
			continue
		}
		return applyRawConfig(name, []byte(c.Prev), "restored the configuration from "+
			at.Format("2 Jan 15:04"))
	}
	return fmt.Errorf("no configuration from %s is kept for %q", at.Format("2 Jan 15:04"), name)
}

func editConfigHistory(name string) {
	hist := ConfigHistory(name)
	if len(hist) == 0 {
		fmt.Println()
		tui.Info("Nothing has been changed on this tunnel yet, so there is nothing to go back to.")
		tui.PressEnter()
		return
	}

	tui.Clear()
	tui.Title("Undo a change · " + name)
	fmt.Println()
	tui.Info("Each entry is the configuration as it was BEFORE the change made at")
	tui.Info("that moment. Restoring puts that configuration back and restarts the")
	tui.Info("tunnel on it — and if it will not come up, it is reverted, exactly")
	tui.Info("like any other change.")
	fmt.Println()

	opts := make([]tui.Option, 0, len(hist))
	for _, c := range hist {
		desc := "the configuration in place before this"
		if c.Note != "" {
			desc = c.Note
		}
		opts = append(opts, tui.Option{
			Title: "Before " + c.At.Format("2 Jan 15:04:05"),
			Desc:  desc,
		})
	}

	idx := tui.ChooseOpt("Go back to which?", opts)
	if idx < 0 || idx >= len(hist) {
		return
	}
	chosen := hist[idx]

	fmt.Println()
	tui.Warn("This restarts the tunnel, so connections through it drop for a moment.")
	fmt.Println()
	if !tui.Confirm("Restore the configuration from before "+chosen.At.Format("2 Jan 15:04:05"), false) {
		return
	}
	if err := RestoreConfigFrom(name, chosen.At); err != nil {
		tui.Error(err.Error())
		tui.PressEnter()
		return
	}
	tui.Success("Restored, and the tunnel came up on it.")
	tui.PressEnter()
}