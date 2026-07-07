package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/store"
)

func TestJobsCreateAndGet(t *testing.T) {
	inbox, err := store.OpenInboxStore(t.TempDir() + "/inbox.db")
	if err != nil {
		t.Fatal(err)
	}
	defer inbox.Close()
	js, err := store.NewJobStoreFromDB(inbox.DB())
	if err != nil {
		t.Fatal(err)
	}
	h := NewJobsHandler(config.DefaultConfig(), js)

	body := map[string]any{
		"user_id":             "user-xyz",
		"scheduler_agent_id":  "lingji-pc",
		"intent":              "test transfer",
		"playbook":            "fleet.file_transfer",
		"plan": map[string]any{
			"sender_agent_id":   "lingji-laptop",
			"receiver_agent_id": "lingji-pc",
			"file_hint":         "a.txt",
		},
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/v1/jobs", bytes.NewReader(raw))
	rec := httptest.NewRecorder()
	h.HandleCreate(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create: %d %s", rec.Code, rec.Body.String())
	}
	var created map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}
	jobID, _ := created["job_id"].(string)
	if jobID == "" {
		t.Fatalf("missing job_id: %+v", created)
	}

	getReq := httptest.NewRequest(http.MethodGet, "/v1/jobs/"+jobID, nil)
	getRec := httptest.NewRecorder()
	h.HandleGet(getRec, getReq)
	if getRec.Code != http.StatusOK {
		t.Fatalf("get: %d %s", getRec.Code, getRec.Body.String())
	}
}
