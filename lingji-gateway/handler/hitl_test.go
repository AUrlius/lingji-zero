package handler_test

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/handler"
	"github.com/AUrlius/lingji-gateway/store"
)

func TestHitlHandlerPendingAndRespond(t *testing.T) {
	path := filepath.Join(t.TempDir(), "inbox.db")
	inbox, err := store.OpenInboxStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer inbox.Close()

	hitl, err := store.NewHitlPendingFromDB(inbox.DB())
	if err != nil {
		t.Fatal(err)
	}
	_ = hitl.UpsertPending(&store.HitlPending{
		TaskID:      "t-hitl-1",
		UserID:      "user-1",
		AgentID:     "lingji-laptop",
		ThreadID:    "user-1:42",
		Description: "test approval",
		Tool:        "execute_command",
		RiskLevel:   "critical",
	})

	cfg := &config.Config{AuthToken: "tok"}
	h := handler.NewHitlHandler(cfg, hitl)

	req := httptest.NewRequest(http.MethodGet, "/v1/hitl/pending?user_id=user-1&token=tok", nil)
	rec := httptest.NewRecorder()
	h.HandlePending(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("pending status = %d body=%s", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	raw, ok := body["pending"].([]any)
	if !ok || len(raw) != 1 {
		t.Fatalf("pending = %#v", body["pending"])
	}

	payload, _ := json.Marshal(map[string]string{
		"task_id":         "t-hitl-1",
		"decision":        "approved",
		"target_agent_id": "lingji-laptop",
	})
	req2 := httptest.NewRequest(http.MethodPost, "/v1/hitl/respond?token=tok", bytes.NewReader(payload))
	rec2 := httptest.NewRecorder()
	h.HandleRespond(rec2, req2)
	if rec2.Code != http.StatusOK {
		t.Fatalf("respond status = %d", rec2.Code)
	}

	req3 := httptest.NewRequest(http.MethodGet, "/v1/hitl/pending?user_id=user-1&token=tok", nil)
	rec3 := httptest.NewRecorder()
	h.HandlePending(rec3, req3)
	if err := json.Unmarshal(rec3.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	raw, ok = body["pending"].([]any)
	if !ok || len(raw) != 0 {
		t.Fatalf("after respond pending = %#v", body["pending"])
	}
}

func TestCaptureHitlMessageReqAndRes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "inbox.db")
	inbox, err := store.OpenInboxStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer inbox.Close()

	hitl, err := store.NewHitlPendingFromDB(inbox.DB())
	if err != nil {
		t.Fatal(err)
	}

	reqRaw := []byte(`{
		"msg_type":"HITL_REQ",
		"device_id":"lingji-laptop",
		"payload":{
			"task_id":"cap-1",
			"target_user_id":"user-cap",
			"agent_id":"lingji-laptop",
			"thread_id":"user-cap:1",
			"description":"rm -rf",
			"tool":"execute_command",
			"risk_level":"critical"
		}
	}`)
	handler.CaptureHitlMessage(hitl, "HITL_REQ", "lingji-laptop", reqRaw)

	items, err := hitl.ListPending("user-cap")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].TaskID != "cap-1" {
		t.Fatalf("after REQ: %+v", items)
	}

	resRaw := []byte(`{
		"msg_type":"HITL_RES",
		"device_id":"web-conn",
		"payload":{"task_id":"cap-1","decision":"approved"}
	}`)
	handler.CaptureHitlMessage(hitl, "HITL_RES", "web-conn", resRaw)

	items, err = hitl.ListPending("user-cap")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 0 {
		t.Fatalf("after RES pending len = %d", len(items))
	}
}
