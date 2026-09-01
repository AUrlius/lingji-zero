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

	_ = hitl.UpsertPending(&store.HitlPending{
		TaskID:           "t-sched-hide",
		UserID:           "user-1",
		AgentID:          "lingji-pc",
		Escalation:       "scheduler",
		SchedulerAgentID: "lingji-laptop",
		JobID:            "LJ-HIDE",
	})

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

	reqSched := httptest.NewRequest(http.MethodGet, "/v1/hitl/pending?user_id=user-1&escalation=scheduler&token=tok", nil)
	recSched := httptest.NewRecorder()
	h.HandlePending(recSched, reqSched)
	if recSched.Code != http.StatusOK {
		t.Fatalf("scheduler pending status = %d", recSched.Code)
	}
	var schedBody map[string]any
	if err := json.Unmarshal(recSched.Body.Bytes(), &schedBody); err != nil {
		t.Fatal(err)
	}
	schedRaw, ok := schedBody["pending"].([]any)
	if !ok || len(schedRaw) != 1 {
		t.Fatalf("scheduler pending = %#v", schedBody["pending"])
	}

	payload, _ := json.Marshal(map[string]string{
		"task_id":         "t-hitl-1",
		"decision":        "approved",
		"target_agent_id": "lingji-laptop",
		"responded_by":    "scheduler",
	})
	req2 := httptest.NewRequest(http.MethodPost, "/v1/hitl/respond?token=tok", bytes.NewReader(payload))
	rec2 := httptest.NewRecorder()
	h.HandleRespond(rec2, req2)
	if rec2.Code != http.StatusOK {
		t.Fatalf("respond status = %d", rec2.Code)
	}
	var respondBody map[string]any
	if err := json.Unmarshal(rec2.Body.Bytes(), &respondBody); err != nil {
		t.Fatal(err)
	}
	if respondBody["responded_by"] != "scheduler" {
		t.Fatalf("responded_by = %#v", respondBody["responded_by"])
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
		"device_id":"lingji-pc",
		"payload":{
			"task_id":"cap-sched",
			"target_user_id":"user-cap",
			"agent_id":"lingji-pc",
			"thread_id":"user-cap:1",
			"description":"uname",
			"tool":"execute_command",
			"risk_level":"critical",
			"job_id":"LJ-CAP",
			"escalation":"scheduler",
			"scheduler_agent_id":"lingji-laptop"
		}
	}`)
	handler.CaptureHitlMessage(hitl, "HITL_REQ", "lingji-pc", reqRaw)

	dock, err := hitl.ListPending("user-cap")
	if err != nil {
		t.Fatal(err)
	}
	if len(dock) != 0 {
		t.Fatalf("scheduler HITL must be hidden from user list: %+v", dock)
	}
	items, err := hitl.ListPendingFiltered("user-cap", "scheduler")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 || items[0].JobID != "LJ-CAP" || items[0].Escalation != "scheduler" {
		t.Fatalf("after REQ: %+v", items)
	}

	resRaw := []byte(`{
		"msg_type":"HITL_RES",
		"device_id":"web-conn",
		"payload":{"task_id":"cap-sched","decision":"approved"}
	}`)
	handler.CaptureHitlMessage(hitl, "HITL_RES", "web-conn", resRaw)

	items, err = hitl.ListPendingFiltered("user-cap", "scheduler")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 0 {
		t.Fatalf("after RES pending len = %d", len(items))
	}
}
