package e2e

import (
	"bytes"
	"context"
	"fmt"
	"net"
	"sync"
	"testing"
	"time"

	"github.com/hasan714222-debug/ParsTanel/internal/client"
	"github.com/hasan714222-debug/ParsTanel/internal/server"
	"github.com/hasan714222-debug/ParsTanel/internal/utils"
)

// The raw UDP transport was the one protocol with no end-to-end coverage: the
// shared harness forwards a TCP echo backend, and UDP needs its own datagram
// path on both ends. This runs a whole udp tunnel — control channel over TCP,
// datagrams over UDP — and proves a packet sent to the entry comes back from
// the backend unchanged.

func startUDPEchoBackend(t *testing.T) string {
	t.Helper()
	pc, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("cannot start the udp echo backend: %v", err)
	}
	t.Cleanup(func() { pc.Close() })
	go func() {
		buf := make([]byte, 64*1024)
		for {
			n, addr, err := pc.ReadFrom(buf)
			if err != nil {
				return
			}
			_, _ = pc.WriteTo(buf[:n], addr)
		}
	}()
	return pc.LocalAddr().String()
}

func TestUDPTransportCarriesData(t *testing.T) {
	backendAddr := startUDPEchoBackend(t)

	tunnelPort := freePort(t)
	entryPort := freePort(t)
	token := "udp-token-0123456789abcdefghij"

	srvCfg := baseServerConfig("udp", tunnelPort, entryPort, backendAddr, token)
	cliCfg := baseClientConfig("udp", fmt.Sprintf("127.0.0.1:%d", tunnelPort), token, nil)

	ctx, cancel := context.WithCancel(context.Background())
	var wg sync.WaitGroup
	t.Cleanup(func() { cancel(); wg.Wait() })

	srv := server.NewServer(srvCfg, ctx)
	wg.Add(1)
	go func() { defer wg.Done(); srv.Start() }()

	time.Sleep(300 * time.Millisecond)

	cli := client.NewClient(cliCfg, ctx)
	wg.Add(1)
	go func() { defer wg.Done(); cli.Start() }()

	entry := fmt.Sprintf("127.0.0.1:%d", entryPort)
	payload := []byte("udp-datagram-roundtrip-check")

	deadline := time.Now().Add(tunnelReadyTimeout)
	var lastErr error
	for time.Now().Before(deadline) {
		if err := udpRoundTrip(entry, payload); err == nil {
			return // success: the udp transport carried the datagram
		} else {
			lastErr = err
		}
		time.Sleep(250 * time.Millisecond)
	}
	t.Fatalf("udp tunnel never carried a datagram: %v", lastErr)
}

// TestUDPServerReadoptsControlChannel proves the server keeps accepting control
// channel claims after the first one is established.
func TestUDPServerReadoptsControlChannel(t *testing.T) {
	backendAddr := startUDPEchoBackend(t)

	tunnelPort := freePort(t)
	entryPort := freePort(t)
	token := "udp-token-0123456789abcdefghij"

	srvCfg := baseServerConfig("udp", tunnelPort, entryPort, backendAddr, token)
	cliCfg := baseClientConfig("udp", fmt.Sprintf("127.0.0.1:%d", tunnelPort), token, nil)

	ctx, cancel := context.WithCancel(context.Background())
	var wg sync.WaitGroup
	t.Cleanup(func() { cancel(); wg.Wait() })

	srv := server.NewServer(srvCfg, ctx)
	wg.Add(1)
	go func() { defer wg.Done(); srv.Start() }()

	time.Sleep(300 * time.Millisecond)

	cli := client.NewClient(cliCfg, ctx)
	wg.Add(1)
	go func() { defer wg.Done(); cli.Start() }()

	entry := fmt.Sprintf("127.0.0.1:%d", entryPort)
	payload := []byte("udp-datagram-roundtrip-check")
	deadline := time.Now().Add(tunnelReadyTimeout)
	up := false
	for time.Now().Before(deadline) {
		if err := udpRoundTrip(entry, payload); err == nil {
			up = true
			break
		}
		time.Sleep(250 * time.Millisecond)
	}
	if !up {
		t.Fatal("udp tunnel never came up")
	}

	claim, err := net.Dial("tcp", fmt.Sprintf("127.0.0.1:%d", tunnelPort))
	if err != nil {
		t.Fatalf("cannot dial the control port: %v", err)
	}
	defer claim.Close()
	if err := claim.SetDeadline(time.Now().Add(3 * time.Second)); err != nil {
		t.Fatalf("cannot set deadline: %v", err)
	}
	if err := utils.SendBinaryTransportString(claim, token, utils.SG_Chan); err != nil {
		t.Fatalf("cannot send the control claim: %v", err)
	}
	msg, signal, err := utils.ReceiveBinaryTransportString(claim)
	if err != nil {
		t.Fatalf("server never answered a second control channel claim (re-adopt broken): %v", err)
	}
	if signal != utils.SG_Chan || msg != token {
		t.Fatalf("unexpected control handshake answer: signal=%d msg=%q", signal, msg)
	}
}

func udpRoundTrip(entry string, payload []byte) error {
	conn, err := net.Dial("udp", entry)
	if err != nil {
		return err
	}
	defer conn.Close()
	if err := conn.SetDeadline(time.Now().Add(2 * time.Second)); err != nil {
		return err
	}
	if _, err := conn.Write(payload); err != nil {
		return err
	}
	got := make([]byte, len(payload))
	n, err := conn.Read(got)
	if err != nil {
		return err
	}
	if !bytes.Equal(payload, got[:n]) {
		return fmt.Errorf("datagram came back corrupted")
	}
	return nil
}
