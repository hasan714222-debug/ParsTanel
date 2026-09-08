package manage

import (
	"fmt"

	"github.com/hasan714222-debug/ParsTanel/internal/tui"
)

func SetupIran() {
	switch askDirection("Iran") {
	case directionReverse:
		SetupServer()
	case directionDirect:
		setupDirectFor(sideIran)
	}
}

func SetupKharej() {
	switch askDirection("Kharej") {
	case directionReverse:
		SetupClient()
	case directionDirect:
		setupDirectFor(sideKharej)
	}
}

type tunnelDirection int

const (
	directionCancelled tunnelDirection = iota
	directionReverse
	directionDirect
)

func askDirection(machine string) tunnelDirection {
	tui.Clear()
	tui.Title("Setup " + machine)
	tui.Warn("Both directions expose the same ports on Iran and keep the real")
	tui.Warn("service on kharej. What changes is which machine reaches out first.")
	fmt.Println()

	switch tui.ChooseOpt("Which direction should the tunnel be built in?", []tui.Option{
		{
			Title: "Reverse",
			Desc:  "kharej dials Iran — the usual choice, and what to try first",
		},
		{
			Title: "Direct",
			Desc:  "Iran dials kharej — use it when an inbound connection to Iran does not get through",
		},
	}) {
	case 0:
		return directionReverse
	case 1:
		return directionDirect
	}
	return directionCancelled
}

func setupDirectFor(side directSide) {
	tui.Clear()
	tui.Title("Direct Tunnel — " + sideName(side))
	tui.Warn("The Iran server dials out to kharej, instead of waiting to be dialled.")
	fmt.Println()

	setupL3(side)
}

func sideName(s directSide) string {
	if s == sideIran {
		return "Iran"
	}
	return "Kharej"
}