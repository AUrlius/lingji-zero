package hub

import (
	"testing"
	"time"
)

func TestHubSendToUserMultiConnection(t *testing.T) {
	h, cleanup := newTestHub(30 * time.Second)
	defer cleanup()

	sendA := make(chan []byte, 8)
	sendB := make(chan []byte, 8)
	cA := &Client{DeviceID: "conn-a", UserID: "user-1", Send: sendA, LastBeat: time.Now()}
	cB := &Client{DeviceID: "conn-b", UserID: "user-1", Send: sendB, LastBeat: time.Now()}
	cOther := &Client{DeviceID: "conn-x", UserID: "user-2", Send: make(chan []byte, 8), LastBeat: time.Now()}

	h.Register(cA)
	h.Register(cB)
	h.Register(cOther)
	time.Sleep(15 * time.Millisecond)

	payload := []byte(`{"msg_type":"AGENT_RES","payload":{"text":"hi"}}`)
	if n := h.SendToUser("user-1", payload); n != 2 {
		t.Fatalf("SendToUser sent=%d want 2", n)
	}

	select {
	case got := <-sendA:
		if string(got) != string(payload) {
			t.Fatalf("conn-a payload mismatch")
		}
	default:
		t.Fatal("conn-a should receive fan-out")
	}
	select {
	case got := <-sendB:
		if string(got) != string(payload) {
			t.Fatalf("conn-b payload mismatch")
		}
	default:
		t.Fatal("conn-b should receive fan-out")
	}

	select {
	case <-cOther.Send:
		t.Fatal("user-2 should not receive user-1 fan-out")
	default:
	}
}
