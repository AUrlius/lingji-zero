package handler_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/handler"
	"github.com/AUrlius/lingji-gateway/hub"
)

func TestAgentsHandlerListsOnlineAgents(t *testing.T) {
	h := hub.New(120 * time.Second)
	go h.Run()
	defer h.Stop()

	h.Register(&hub.Client{DeviceID: "lingji-pc", Send: make(chan []byte, 1), LastBeat: time.Now()})
	h.Register(&hub.Client{DeviceID: "lingji-laptop", Send: make(chan []byte, 1), LastBeat: time.Now()})
	h.Register(&hub.Client{DeviceID: "phone-abc", Send: make(chan []byte, 1), LastBeat: time.Now()})
	time.Sleep(10 * time.Millisecond)

	cfg := config.DefaultConfig()
	agents := handler.NewAgentsHandler(h, cfg)

	req := httptest.NewRequest(http.MethodGet, "/v1/agents", nil)
	rec := httptest.NewRecorder()
	agents.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}

	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body["default_agent_id"] != "lingji-pc" {
		t.Fatalf("default_agent_id = %v", body["default_agent_id"])
	}

	rawAgents, ok := body["agents"].([]any)
	if !ok || len(rawAgents) != 2 {
		t.Fatalf("agents = %#v, want 2 lingji-* entries", body["agents"])
	}
}
