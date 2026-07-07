package handler

import (
	"encoding/json"
	"net/http"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/store"
)

// HitlHandler serves HITL pending inbox HTTP API.
type HitlHandler struct {
	config *config.Config
	hitl   *store.HitlPendingStore
}

func NewHitlHandler(cfg *config.Config, hitl *store.HitlPendingStore) *HitlHandler {
	return &HitlHandler{config: cfg, hitl: hitl}
}

func (h *HitlHandler) authOK(r *http.Request) bool {
	if h.config.AuthToken == "" {
		return true
	}
	if auth := r.Header.Get("Authorization"); auth == "Bearer "+h.config.AuthToken {
		return true
	}
	return r.URL.Query().Get("token") == h.config.AuthToken
}

// HandlePending GET /v1/hitl/pending?user_id=user-xxx
func (h *HitlHandler) HandlePending(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	if h.hitl == nil {
		http.Error(w, "hitl store unavailable", http.StatusServiceUnavailable)
		return
	}
	userID := r.URL.Query().Get("user_id")
	if userID == "" {
		http.Error(w, "user_id required", http.StatusBadRequest)
		return
	}
	items, err := h.hitl.ListPending(userID)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if items == nil {
		items = []store.HitlPending{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"pending": items})
}

// HandleRespond POST /v1/hitl/respond — optional HTTP path for HITL_RES fan-out.
func (h *HitlHandler) HandleRespond(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	var body struct {
		TaskID        string `json:"task_id"`
		Decision      string `json:"decision"`
		TargetAgentID string `json:"target_agent_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if body.TaskID == "" || body.Decision == "" {
		http.Error(w, "task_id and decision required", http.StatusBadRequest)
		return
	}
	if h.hitl != nil {
		status := "resolved"
		if body.Decision == "rejected" {
			status = "rejected"
		}
		_ = h.hitl.Resolve(body.TaskID, status)
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
}
