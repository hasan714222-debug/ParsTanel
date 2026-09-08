package transport

import (
	"net"
	"sync/atomic"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/utils"
	"github.com/hasan714222-debug/ParsTanel/internal/utils/network"

	"github.com/sirupsen/logrus"
)

const controlAckTimeout = 15 * time.Second

const (
	controlIdleFallback = 120 * time.Second
	controlIdleFloor    = 30 * time.Second
)

func controlDeadline(keepAlive time.Duration) time.Duration {
	if keepAlive <= 0 {
		return controlIdleFallback
	}
	if d := keepAlive + keepAlive/2; d > controlIdleFloor {
		return d
	}
	return controlIdleFloor
}

const legacyMissThreshold = 2

type legacyProbe struct {
	legacy   atomic.Bool
	answered atomic.Bool
	misses   atomic.Int32
	warned   atomic.Bool
}

func (p *legacyProbe) signal() byte {
	if p.legacy.Load() {
		return utils.SG_Chan
	}
	return utils.SG_ChanV2
}

func (p *legacyProbe) ack(ackSignal byte) {
	p.misses.Store(0)
	if ackSignal == utils.SG_ChanV2 {
		p.answered.Store(true)
		p.legacy.Store(false)
	}
}

func (p *legacyProbe) miss(logger *logrus.Logger, sent byte) {
	if sent != utils.SG_ChanV2 {
		return
	}
	if p.answered.Load() {
		return
	}
	if p.misses.Add(1) < legacyMissThreshold {
		return
	}
	if p.legacy.Swap(true) || p.warned.Swap(true) {
		return
	}
	logger.Warnf("the server closed %d handshake attempts without answering the current one. "+
		"That is what an older server does, so this client is falling back to the previous "+
		"handshake, in which the server identifies pool connections by their source address — "+
		"which fails if this machine dials out from more than one address (carrier-grade NAT, a multi-homed host, a SNAT pool). Upgrade the client to authorise them by token instead.", legacyMissThreshold)
}

func (p *legacyProbe) reset() {
	p.legacy.Store(false)
	p.misses.Store(0)
}

func refusalReason(ack string, signal byte) (string, bool) {
	if signal != utils.SG_Refused {
		return "", false
	}
	switch ack {
	case utils.RefusedBadToken:
		return "the server rejected the token — the two ends do not have the same one", true
	case utils.RefusedInUse:
		return "the server already has a control channel from somebody else. Two clients " +
			"dialling one server with the same token do this, and so does an old service " +
			"left running beside its replacement", true
	default:
		return "the server refused the handshake: " + ack, true
	}
}

func decodeControlAck(ack string, signal byte) (token, nonce string, muxVersion int) {
	if signal != utils.SG_ChanV2 {
		return ack, "", 0
	}
	return network.DecodeControlAck(ack)
}

func announcePoolConn(conn net.Conn, nonce string) error {
	if nonce == "" {
		return nil
	}
	return utils.SendBinaryTransportString(conn, nonce, utils.SG_Pool)
}