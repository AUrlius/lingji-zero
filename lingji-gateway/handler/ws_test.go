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
	fleet := NewFleetHandler(h, config.DefaultConfig(), q, nil, nil, nil)
	ws := NewWSHandler(h, config.DefaultConfig(), q, nil, nil, fleet)

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

func TestDeliverDownstreamTargetUser(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	fleet := NewFleetHandler(h, config.DefaultConfig(), q, nil, nil, nil)
	ws := NewWSHandler(h, config.DefaultConfig(), q, nil, nil, fleet)

	chA := make(chan []byte, 4)
	chB := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "conn-a", UserID: "user-1", Send: chA, LastBeat: time.Now()})
	h.Register(&hub.Client{DeviceID: "conn-b", UserID: "user-1", Send: chB, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	msg := protocol.NewMessage(protocol.MsgAgentRes, "lingji-pc", map[string]any{
		"text":             "fleet fan-out",
		"target_user_id":   "user-1",
		"target_device_id": "conn-a",
	})
	raw, err := msg.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.deliverDownstream([]byte(raw))

	for name, ch := range map[string]chan []byte{"conn-a": chA, "conn-b": chB} {
		select {
		case got := <-ch:
			if string(got) != raw {
				t.Fatalf("%s got unexpected payload", name)
			}
		default:
			t.Fatalf("%s should receive user fan-out", name)
		}
	}
}

func TestDeliverDownstreamBroadcastFallback(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	fleet := NewFleetHandler(h, config.DefaultConfig(), q, nil, nil, nil)
	ws := NewWSHandler(h, config.DefaultConfig(), q, nil, nil, fleet)

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
	fleet := NewFleetHandler(h, config.DefaultConfig(), q, nil, nil, nil)
	ws := NewWSHandler(h, config.DefaultConfig(), q, nil, nil, fleet)

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

func TestRouteToTargetAgent(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	fleet := NewFleetHandler(h, config.DefaultConfig(), q, nil, nil, nil)
	ws := NewWSHandler(h, config.DefaultConfig(), q, nil, nil, fleet)

	pcCh := make(chan []byte, 4)
	laptopCh := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "lingji-pc", Send: pcCh, LastBeat: time.Now()})
	h.Register(&hub.Client{DeviceID: "lingji-laptop", Send: laptopCh, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	cmd := protocol.NewMessage(protocol.MsgCmdText, "phone-1", map[string]any{
		"text":            "hello laptop",
		"target_agent_id": "lingji-laptop",
	})
	raw, err := cmd.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.routeMessage(protocol.MsgCmdText, "phone-1", []byte(raw))

	select {
	case got := <-laptopCh:
		if string(got) != raw {
			t.Fatalf("laptop got unexpected payload: %s", got)
		}
	default:
		t.Fatal("lingji-laptop should receive targeted CMD_TEXT")
	}

	select {
	case <-pcCh:
		t.Fatal("lingji-pc should not receive laptop-targeted CMD_TEXT")
	default:
	}
}

func TestRouteHermesSessionAlwaysLaptop(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	fleet := NewFleetHandler(h, config.DefaultConfig(), q, nil, nil, nil)
	ws := NewWSHandler(h, config.DefaultConfig(), q, nil, nil, fleet)

	pcCh := make(chan []byte, 4)
	laptopCh := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "lingji-pc", Send: pcCh, LastBeat: time.Now()})
	h.Register(&hub.Client{DeviceID: "lingji-laptop", Send: laptopCh, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	cmd := protocol.NewMessage(protocol.MsgCmdHermesSession, "phone-1", map[string]any{
		"action":          "start",
		"target_agent_id": "lingji-pc",
	})
	raw, err := cmd.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.routeMessage(protocol.MsgCmdHermesSession, "phone-1", []byte(raw))

	select {
	case got := <-laptopCh:
		if string(got) != raw {
			t.Fatalf("laptop got unexpected payload: %s", got)
		}
	default:
		t.Fatal("CMD_HERMES_SESSION must go to lingji-laptop")
	}

	select {
	case <-pcCh:
		t.Fatal("lingji-pc must not receive CMD_HERMES_SESSION")
	default:
	}
}

func TestRouteHermesSessionOfflineQueuesLaptop(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	fleet := NewFleetHandler(h, config.DefaultConfig(), q, nil, nil, nil)
	ws := NewWSHandler(h, config.DefaultConfig(), q, nil, nil, fleet)

	cmd := protocol.NewMessage(protocol.MsgCmdHermesSession, "phone-1", map[string]any{
		"action": "health",
	})
	raw, err := cmd.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.routeMessage(protocol.MsgCmdHermesSession, "phone-1", []byte(raw))

	queued := q.DequeueAll("lingji-laptop")
	if len(queued) != 1 || queued[0] != raw {
		t.Fatalf("expected laptop offline queue, got %#v", queued)
	}
	if q.Len("lingji-pc") != 0 {
		t.Fatal("must not queue CMD_HERMES_SESSION for lingji-pc")
	}
}

func TestRouteDefaultAgent(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	fleet := NewFleetHandler(h, config.DefaultConfig(), q, nil, nil, nil)
	ws := NewWSHandler(h, config.DefaultConfig(), q, nil, nil, fleet)

	pcCh := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "lingji-pc", Send: pcCh, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	cmd := protocol.NewMessage(protocol.MsgCmdText, "phone-1", map[string]any{
		"text": "hello default",
	})
	raw, err := cmd.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.routeMessage(protocol.MsgCmdText, "phone-1", []byte(raw))

	select {
	case got := <-pcCh:
		if string(got) != raw {
			t.Fatalf("pc got unexpected payload: %s", got)
		}
	default:
		t.Fatal("lingji-pc should receive default CMD_TEXT")
	}
}

func TestIsAgentDevice(t *testing.T) {
	if !IsAgentDevice("lingji-pc") || !IsAgentDevice("lingji-laptop") {
		t.Fatal("lingji-* should be agent devices")
	}
	if IsAgentDevice("phone-abc") || IsAgentDevice("pending-127.0.0.1") {
		t.Fatal("non lingji-* should not be agent devices")
	}
}

func TestDeliverDownstreamSchedulerHitlSkipsUser(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	q := queue.NewOfflineQueue(16)
	fleet := NewFleetHandler(h, config.DefaultConfig(), q, nil, nil, nil)
	ws := NewWSHandler(h, config.DefaultConfig(), q, nil, nil, fleet)

	userCh := make(chan []byte, 4)
	schedCh := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "web-1", UserID: "user-1", Send: userCh, LastBeat: time.Now()})
	h.Register(&hub.Client{DeviceID: "lingji-laptop", Send: schedCh, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	msg := protocol.NewMessage(protocol.MsgHitlReq, "lingji-pc", map[string]any{
		"task_id":            "t-del",
		"target_user_id":     "user-1",
		"escalation":         "scheduler",
		"scheduler_agent_id": "lingji-laptop",
		"agent_id":           "lingji-pc",
	})
	raw, err := msg.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.deliverDownstream([]byte(raw))

	select {
	case got := <-schedCh:
		if string(got) != raw {
			t.Fatalf("scheduler got unexpected payload")
		}
	default:
		t.Fatal("lingji-laptop should receive delegated HITL_REQ")
	}
	select {
	case <-userCh:
		t.Fatal("user dock should not receive escalation=scheduler HITL_REQ")
	default:
	}
}
