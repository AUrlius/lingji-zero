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

func TestJobsListDispatchReport(t *testing.T) {
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
		"user_id":            "user-xyz",
		"scheduler_agent_id": "lingji-laptop",
		"intent":             "status check",
		"playbook":           "agent.status",
		"plan":               map[string]any{"executor_id": "lingji-pc"},
	}
	raw, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/v1/jobs", bytes.NewReader(raw))
	rec := httptest.NewRecorder()
	h.HandleCreate(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("create: %d %s", rec.Code, rec.Body.String())
	}
	var created store.Job
	if err := json.Unmarshal(rec.Body.Bytes(), &created); err != nil {
		t.Fatal(err)
	}

	listReq := httptest.NewRequest(http.MethodGet, "/v1/jobs?user_id=user-xyz", nil)
	listRec := httptest.NewRecorder()
	h.HandleList(listRec, listReq)
	if listRec.Code != http.StatusOK {
		t.Fatalf("list: %d %s", listRec.Code, listRec.Body.String())
	}

	dispReq := httptest.NewRequest(http.MethodPost, "/v1/jobs/"+created.JobID+"/dispatch", bytes.NewReader([]byte(`{}`)))
	dispReq.SetPathValue("job_id", created.JobID)
	dispRec := httptest.NewRecorder()
	h.HandleDispatch(dispRec, dispReq)
	if dispRec.Code != http.StatusOK {
		t.Fatalf("dispatch: %d %s", dispRec.Code, dispRec.Body.String())
	}

	stepID := created.JobID + "-S1"
	repRaw, _ := json.Marshal(map[string]any{"status": "completed", "evidence": map[string]any{"ok": true}})
	repReq := httptest.NewRequest(http.MethodPost, "/v1/jobs/"+created.JobID+"/steps/"+stepID+"/report", bytes.NewReader(repRaw))
	repReq.SetPathValue("job_id", created.JobID)
	repReq.SetPathValue("step_id", stepID)
	repRec := httptest.NewRecorder()
	h.HandleReport(repRec, repReq)
	if repRec.Code != http.StatusOK {
		t.Fatalf("report: %d %s", repRec.Code, repRec.Body.String())
	}
	var done store.Job
	if err := json.Unmarshal(repRec.Body.Bytes(), &done); err != nil {
		t.Fatal(err)
	}
	if done.Status != "completed" {
		t.Fatalf("status=%s", done.Status)
	}
}
