package manage

import (
	"os"
	"strings"

	"github.com/hasan714222-debug/ParsTanel/internal/app"
	"github.com/hasan714222-debug/ParsTanel/internal/tui"
)

// Release channels.
const (
	ChannelStable = "stable"
	ChannelBeta   = "beta"
)

var channelFile = app.ConfigDir + "/channel"

var channelOptions = []struct {
	label, desc, value string
}{
	{"Stable", "finished releases only — recommended", ChannelStable},
	{"Beta", "also installs pre-releases — for testing before everyone else", ChannelBeta},
}

func Channel() string {
	b, err := os.ReadFile(channelFile)
	if err != nil {
		return ChannelStable
	}
	if strings.TrimSpace(string(b)) == ChannelBeta {
		return ChannelBeta
	}
	return ChannelStable
}

func SetChannel(channel string) error {
	if channel != ChannelBeta {
		channel = ChannelStable
	}
	if err := os.MkdirAll(app.ConfigDir, 0755); err != nil {
		return err
	}
	return os.WriteFile(channelFile, []byte(channel+"\n"), 0644)
}

func ChannelLabel() string { return channelLabel(Channel()) }

func ChannelOptions() ([]tui.Option, []string) {
	opts := make([]tui.Option, len(channelOptions))
	values := make([]string, len(channelOptions))
	for i, o := range channelOptions {
		opts[i] = tui.Option{Title: o.label, Desc: o.desc}
		values[i] = o.value
	}
	return opts, values
}

func channelLabel(value string) string {
	for _, o := range channelOptions {
		if o.value == value {
			return o.label
		}
	}
	return value
}

func isPrerelease(tag string) bool {
	v := strings.TrimPrefix(strings.TrimSpace(tag), "v")
	return strings.ContainsAny(v, "-+")
}
