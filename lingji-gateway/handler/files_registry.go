package handler

import (
	"encoding/json"
	"net/http"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/store"
)

type FileRegistryHandler struct {
	config   *config.Config
	registry *store.FileRegistryStore
}

func NewFileRegistryHandler(cfg *config.Config, reg *store.FileRegistryStore) *FileRegistryHandler {
	return &FileRegistryHandler{config: cfg, registry: reg}
}

func (h *FileRegistryHandler) authOK(r *http.Request) bool {
	if h.config.AuthToken == "" {
		return true
	}
	if auth := r.Header.Get("Authorization"); auth == "Bearer "+h.config.AuthToken {
		return true
	}
	return r.URL.Query().Get("token") == h.config.AuthToken
}

func (h *FileRegistryHandler) HandleRegister(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	if h.registry == nil {
		http.Error(w, "registry unavailable", http.StatusServiceUnavailable)
		return
	}
	var body struct {
		LingjiFileID  string `json:"lingji_file_id"`
		UserID        string `json:"user_id"`
		Name          string `json:"name"`
		SizeBytes     int64  `json:"size_bytes"`
		Mime          string `json:"mime"`
		HolderAgentID string `json:"holder_agent_id"`
		LocalPath     string `json:"local_path"`
		GatewayFileID string `json:"gateway_file_id"`
		SourceAgentID string `json:"source_agent_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if body.UserID == "" || body.Name == "" {
		http.Error(w, "user_id and name required", http.StatusBadRequest)
		return
	}
	entry := store.LingjiFile{
		LingjiFileID:  body.LingjiFileID,
		UserID:        body.UserID,
		Name:          body.Name,
		SizeBytes:     body.SizeBytes,
		Mime:          body.Mime,
		HolderAgentID: body.HolderAgentID,
		LocalPath:     body.LocalPath,
		GatewayFileID: body.GatewayFileID,
		SourceAgentID: body.SourceAgentID,
	}
	if err := h.registry.Register(&entry); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if entry.LingjiFileID == "" {
		http.Error(w, "register failed", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"lingji_file_id": entry.LingjiFileID,
		"status":         "registered",
	})
}

func (h *FileRegistryHandler) HandleGet(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	userID := r.URL.Query().Get("user_id")
	lfID := r.URL.Query().Get("lingji_file_id")
	if userID == "" || lfID == "" {
		http.Error(w, "user_id and lingji_file_id required", http.StatusBadRequest)
		return
	}
	f, err := h.registry.Get(userID, lfID)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(f)
}
