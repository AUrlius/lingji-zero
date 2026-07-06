package handler_test

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/handler"
	"github.com/AUrlius/lingji-gateway/store"
)

func TestInboxHandlerThreadsAndMessages(t *testing.T) {
	path := filepath.Join(t.TempDir(), "inbox.db")
	inbox, err := store.OpenInboxStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer inbox.Close()

	_ = inbox.UpsertThread("t1", "user-1", "lingji-pc", "Title")
	_ = inbox.AppendMessage("t1", "user-1", "lingji-pc", "user", "hello", "web")

	cfg := &config.Config{AuthToken: "tok"}
	h := handler.NewInboxHandler(cfg, inbox)

	req := httptest.NewRequest(http.MethodGet, "/v1/inbox/threads?user_id=user-1&token=tok", nil)
	rec := httptest.NewRecorder()
	h.HandleThreads(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("threads status = %d", rec.Code)
	}
	var threadsBody map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &threadsBody); err != nil {
		t.Fatal(err)
	}
	rawThreads, ok := threadsBody["threads"].([]any)
	if !ok || len(rawThreads) != 1 {
		t.Fatalf("threads = %#v", threadsBody["threads"])
	}

	req2 := httptest.NewRequest(http.MethodGet, "/v1/inbox/messages?thread_id=t1&agent_id=lingji-pc&token=tok", nil)
	rec2 := httptest.NewRecorder()
	h.HandleMessages(rec2, req2)
	if rec2.Code != http.StatusOK {
		t.Fatalf("messages status = %d", rec2.Code)
	}
	var msgBody map[string]any
	if err := json.Unmarshal(rec2.Body.Bytes(), &msgBody); err != nil {
		t.Fatal(err)
	}
	rawMsgs, ok := msgBody["messages"].([]any)
	if !ok || len(rawMsgs) != 1 {
		t.Fatalf("messages = %#v", msgBody["messages"])
	}
}

func TestCaptureWSMessageAgentSessions(t *testing.T) {
	path := filepath.Join(t.TempDir(), "inbox.db")
	inbox, err := store.OpenInboxStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer inbox.Close()

	raw := []byte(`{
		"msg_type":"AGENT_RES",
		"device_id":"lingji-laptop",
		"payload":{
			"status":"sessions",
			"target_user_id":"user-xyz",
			"sessions":[{"thread_id":"user-xyz:1","title":"Test"}],
			"text":""
		}
	}`)
	handler.CaptureWSMessage(inbox, "AGENT_RES", "lingji-laptop", raw)

	threads, err := inbox.ListThreads("user-xyz")
	if err != nil {
		t.Fatal(err)
	}
	if len(threads) != 1 || threads[0].AgentID != "lingji-laptop" {
		t.Fatalf("threads = %+v", threads)
	}
}
