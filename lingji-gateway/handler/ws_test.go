package handler

import (
	"testing"
	"time"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/hub"
	"github.com/AUrlius/lingji-gateway/protocol"
	"github.com/AUrlius/lingji-gateway/queue"
)

func TestDeliverDownstreamTargeted(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	ws := NewWSHandler(h, config.DefaultConfig(), q)

	phoneA := make(chan []byte, 4)
	phoneB := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "phone-a", Send: phoneA, LastBeat: time.Now()})
	h.Register(&hub.Client{DeviceID: "phone-b", Send: phoneB, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	msg := protocol.NewMessage(protocol.MsgAgentRes, "lingji-pc", map[string]any{
		"text":             "hello a",
		"target_device_id": "phone-a",
	})
	raw, err := msg.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.deliverDownstream([]byte(raw))

	select {
	case got := <-phoneA:
		if string(got) != raw {
			t.Fatalf("phone-a got unexpected payload: %s", got)
		}
	default:
		t.Fatal("phone-a should receive targeted reply")
	}

	select {
	case <-phoneB:
		t.Fatal("phone-b should not receive targeted reply")
	default:
	}
}

func TestDeliverDownstreamBroadcastFallback(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	ws := NewWSHandler(h, config.DefaultConfig(), q)

	phoneA := make(chan []byte, 4)
	phoneB := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "phone-a", Send: phoneA, LastBeat: time.Now()})
	h.Register(&hub.Client{DeviceID: "phone-b", Send: phoneB, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	msg := protocol.NewMessage(protocol.MsgAgentRes, "lingji-pc", map[string]any{
		"text": "broadcast all",
	})
	raw, err := msg.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.deliverDownstream([]byte(raw))

	if _, ok := <-phoneA; !ok {
		t.Fatal("phone-a should receive broadcast")
	}
	if _, ok := <-phoneB; !ok {
		t.Fatal("phone-b should receive broadcast")
	}
}

func TestDeliverDownstreamOfflineQueue(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	ws := NewWSHandler(h, config.DefaultConfig(), q)

	msg := protocol.NewMessage(protocol.MsgAgentRes, "lingji-pc", map[string]any{
		"text":             "queued",
		"target_device_id": "phone-offline",
	})
	raw, err := msg.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.deliverDownstream([]byte(raw))

	queued := q.DequeueAll("phone-offline")
	if len(queued) != 1 || queued[0] != raw {
		t.Fatalf("expected offline queue entry, got %#v", queued)
	}
}
