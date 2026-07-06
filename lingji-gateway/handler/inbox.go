package handler

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/store"
)

// InboxHandler serves GET /v1/inbox/threads and GET /v1/inbox/messages.
type InboxHandler struct {
	config *config.Config
	inbox  *store.InboxStore
}

// NewInboxHandler creates an inbox HTTP handler.
func NewInboxHandler(cfg *config.Config, inbox *store.InboxStore) *InboxHandler {
	return &InboxHandler{config: cfg, inbox: inbox}
}

func (h *InboxHandler) authOK(r *http.Request) bool {
	if h.config.AuthToken == "" {
		return true
	}
	if auth := r.Header.Get("Authorization"); auth == "Bearer "+h.config.AuthToken {
		return true
	}
	return r.URL.Query().Get("token") == h.config.AuthToken
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}

// HandleThreads GET /v1/inbox/threads?user_id=user-xxx
func (h *InboxHandler) HandleThreads(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	userID := r.URL.Query().Get("user_id")
	if userID == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing user_id"})
		return
	}
	threads, err := h.inbox.ListThreads(userID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "inbox_list_failed"})
		return
	}
	if threads == nil {
		threads = []store.Thread{}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"user_id": userID,
		"threads": threads,
	})
}

// HandleMessages GET /v1/inbox/messages?thread_id=...&agent_id=lingji-pc&limit=200
func (h *InboxHandler) HandleMessages(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	threadID := r.URL.Query().Get("thread_id")
	agentID := r.URL.Query().Get("agent_id")
	if threadID == "" || agentID == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "missing thread_id or agent_id"})
		return
	}
	limit := 200
	if s := r.URL.Query().Get("limit"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			limit = n
		}
	}
	msgs, err := h.inbox.ListMessages(threadID, agentID, limit)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "inbox_messages_failed"})
		return
	}
	if msgs == nil {
		msgs = []store.Message{}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"thread_id": threadID,
		"agent_id":  agentID,
		"messages":  msgs,
	})
}
