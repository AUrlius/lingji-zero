package hub

import (
	"fmt"
	"testing"
	"time"
)

func TestHubStressRegister100(t *testing.T) {
	h, cleanup := newTestHub(30 * time.Second)
	defer cleanup()

	for i := 0; i < 100; i++ {
		id := fmt.Sprintf("stress-device-%d", i)
		c := &Client{
			DeviceID: id,
			Send:     make(chan []byte, 4),
			LastBeat: time.Now(),
		}
		h.Register(c)
	}
	time.Sleep(50 * time.Millisecond)

	if got := h.Len(); got != 100 {
		t.Fatalf("Len() = %d, want 100", got)
	}

	devices := h.OnlineDevices()
	if len(devices) != 100 {
		t.Fatalf("OnlineDevices() = %d, want 100", len(devices))
	}

	// 注销一半
	for i := 0; i < 50; i++ {
		id := fmt.Sprintf("stress-device-%d", i)
		if c := h.GetClient(id); c != nil {
			h.Unregister(c)
		}
	}
	time.Sleep(50 * time.Millisecond)

	if got := h.Len(); got != 50 {
		t.Fatalf("Len() after unregister = %d, want 50", got)
	}
}

func TestHubStressDuplicateKick(t *testing.T) {
	h, cleanup := newTestHub(30 * time.Second)
	defer cleanup()

	send1 := make(chan []byte, 4)
	c1 := &Client{DeviceID: "dup-stress", Send: send1, LastBeat: time.Now()}
	h.Register(c1)
	time.Sleep(20 * time.Millisecond)

	send2 := make(chan []byte, 4)
	c2 := &Client{DeviceID: "dup-stress", Send: send2, LastBeat: time.Now()}
	h.Register(c2)
	time.Sleep(20 * time.Millisecond)

	if h.Len() != 1 {
		t.Fatalf("Len() = %d, want 1", h.Len())
	}
	if h.GetClient("dup-stress") != c2 {
		t.Fatal("active client should be the latest registration")
	}

	select {
	case _, ok := <-send1:
		if ok {
			t.Error("old send channel should be closed")
		}
	default:
		t.Error("old send channel should be closed")
	}
}
