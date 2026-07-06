package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/hub"
	"github.com/AUrlius/lingji-gateway/protocol"
	"github.com/AUrlius/lingji-gateway/queue"
	"github.com/AUrlius/lingji-gateway/store"
)

func testFleetSetup(t *testing.T) (*hub.Hub, *FleetHandler, *WSHandler, *store.InboxStore) {
	t.Helper()
	h := hub.New(120 * time.Second)
	go h.Run()
	t.Cleanup(func() { h.Stop() })

	q := queue.NewOfflineQueue(16)
	inbox, err := store.OpenInboxStore(t.TempDir() + "/inbox.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { inbox.Close() })

	fleet := NewFleetHandler(h, config.DefaultConfig(), q, inbox)
	ws := NewWSHandler(h, config.DefaultConfig(), q, inbox, fleet)
	return h, fleet, ws, inbox
}

func TestFleetTransferToUser(t *testing.T) {
	h, fleet, _, inbox := testFleetSetup(t)

	userCh := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "conn-1", UserID: "user-abc", Send: userCh, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	body := map[string]any{
		"from_agent_id": "lingji-laptop",
		"to_user_id":    "user-abc",
		"thread_id":     "thread-1",
		"user_id":       "user-abc",
		"uploads": []map[string]any{
			{
				"file_id":       "f1",
				"name":          "report.pdf",
				"download_path": "/files/f1?token=tok",
				"size_bytes":    100,
				"mime":          "application/pdf",
			},
		},
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/v1/fleet/transfer", bytes.NewReader(raw))
	rec := httptest.NewRecorder()
	fleet.HandleTransfer(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rec.Code, rec.Body.String())
	}

	select {
	case got := <-userCh:
		var msg protocol.Message
		if err := json.Unmarshal(got, &msg); err != nil {
			t.Fatal(err)
		}
		if msg.MsgType != protocol.MsgAgentRes {
			t.Fatalf("expected AGENT_RES, got %s", msg.MsgType)
		}
		atts, ok := msg.Payload["attachments"].([]any)
		if !ok || len(atts) != 1 {
			t.Fatalf("expected attachments, got %#v", msg.Payload["attachments"])
		}
	default:
		t.Fatal("user should receive AGENT_RES with attachments")
	}

	msgs, err := inbox.ListMessages("thread-1", "lingji-laptop", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(msgs) == 0 {
		t.Fatal("inbox should record fleet transfer")
	}
}

func TestFleetTransferToAgentDeliver(t *testing.T) {
	h, fleet, _, _ := testFleetSetup(t)

	pcCh := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "lingji-pc", Send: pcCh, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	body := map[string]any{
		"from_agent_id": "lingji-laptop",
		"to_agent_id":   "lingji-pc",
		"thread_id":     "thread-2",
		"user_id":       "user-abc",
		"uploads": []map[string]any{
			{"file_id": "f2", "name": "doc.txt", "download_path": "/files/f2?token=tok"},
		},
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/v1/fleet/transfer", bytes.NewReader(raw))
	rec := httptest.NewRecorder()
	fleet.HandleTransfer(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}

	select {
	case got := <-pcCh:
		var msg protocol.Message
		if err := json.Unmarshal(got, &msg); err != nil {
			t.Fatal(err)
		}
		if msg.MsgType != protocol.MsgFleetDeliver {
			t.Fatalf("expected FLEET_DELIVER, got %s", msg.MsgType)
		}
	default:
		t.Fatal("lingji-pc should receive FLEET_DELIVER")
	}
}

func TestFleetTransferToAgentOfflineQueue(t *testing.T) {
	h, _, _, _ := testFleetSetup(t)

	q := queue.NewOfflineQueue(16)
	offlineFleet := NewFleetHandler(h, config.DefaultConfig(), q, nil)

	body := map[string]any{
		"from_agent_id": "lingji-laptop",
		"to_agent_id":   "lingji-pc",
		"user_id":       "user-abc",
		"uploads": []map[string]any{
			{"file_id": "f3", "name": "offline.txt", "download_path": "/files/f3?token=tok"},
		},
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/v1/fleet/transfer", bytes.NewReader(raw))
	rec := httptest.NewRecorder()
	offlineFleet.HandleTransfer(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}

	queued := q.DequeueAll("lingji-pc")
	if len(queued) != 1 {
		t.Fatalf("expected queued FLEET_DELIVER, got %d", len(queued))
	}
	var msg protocol.Message
	if err := json.Unmarshal([]byte(queued[0]), &msg); err != nil {
		t.Fatal(err)
	}
	if msg.MsgType != protocol.MsgFleetDeliver {
		t.Fatalf("expected FLEET_DELIVER in queue, got %s", msg.MsgType)
	}
	_ = h
}

func TestFleetAckFanOut(t *testing.T) {
	h, fleet, ws, inbox := testFleetSetup(t)

	userCh := make(chan []byte, 4)
	h.Register(&hub.Client{DeviceID: "conn-1", UserID: "user-abc", Send: userCh, LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	transferID := "xfer-123"
	fleet.pendingMu.Lock()
	fleet.pending[transferID] = &pendingTransfer{
		FromAgentID: "lingji-laptop",
		ToAgentID:   "lingji-pc",
		UserID:      "user-abc",
		ThreadID:    "thread-3",
		Uploads:     []map[string]any{{"name": "saved.pdf"}},
	}
	fleet.pendingMu.Unlock()

	ack := protocol.NewMessage(protocol.MsgFleetAck, "lingji-pc", map[string]any{
		"transfer_id": transferID,
		"status":      "ok",
		"saved":       []map[string]any{{"name": "saved.pdf", "path": "/tmp/saved.pdf"}},
	})
	raw, err := ack.ToJSON()
	if err != nil {
		t.Fatal(err)
	}
	ws.routeMessage(protocol.MsgFleetAck, "lingji-pc", []byte(raw))

	select {
	case got := <-userCh:
		var msg protocol.Message
		if err := json.Unmarshal(got, &msg); err != nil {
			t.Fatal(err)
		}
		if msg.Payload["fleet_status"] != "ok" {
			t.Fatalf("expected fleet_status ok, got %#v", msg.Payload)
		}
	default:
		t.Fatal("user should receive fleet completion AGENT_RES")
	}

	msgs, err := inbox.ListMessages("thread-3", "lingji-laptop", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(msgs) == 0 {
		t.Fatal("inbox should record fleet ack")
	}
}

func TestFleetTransferValidation(t *testing.T) {
	_, fleet, _, _ := testFleetSetup(t)

	req := httptest.NewRequest(http.MethodPost, "/v1/fleet/transfer", bytes.NewReader([]byte(`{}`)))
	rec := httptest.NewRecorder()
	fleet.HandleTransfer(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}
