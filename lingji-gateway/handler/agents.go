package handler

import (
	"encoding/json"
	"net/http"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/hub"
)

type AgentsHandler struct {
	hub    *hub.Hub
	config *config.Config
}

func NewAgentsHandler(h *hub.Hub, cfg *config.Config) *AgentsHandler {
	return &AgentsHandler{hub: h, config: cfg}
}

func (a *AgentsHandler) authOK(r *http.Request) bool {
	if a.config.AuthToken == "" {
		return true
	}
	if auth := r.Header.Get("Authorization"); auth == "Bearer "+a.config.AuthToken {
		return true
	}
	return r.URL.Query().Get("token") == a.config.AuthToken
}

func (a *AgentsHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !a.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	type agentEntry struct {
		DeviceID    string `json:"device_id"`
		DisplayName string `json:"display_name"`
	}
	agents := make([]agentEntry, 0)
	for _, a := range a.hub.OnlineAgents() {
		agents = append(agents, agentEntry{DeviceID: a.DeviceID, DisplayName: a.DisplayName})
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{
		"agents":           agents,
		"default_agent_id": DefaultAgentID,
	})
}
