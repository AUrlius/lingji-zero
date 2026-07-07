package handler

import (
	"encoding/json"
	"log"

	"github.com/AUrlius/lingji-gateway/store"
)

// CaptureHitlMessage mirrors HITL_REQ / HITL_RES into Gateway hitl_pending store.
func CaptureHitlMessage(hitl *store.HitlPendingStore, msgType string, fromDevice string, raw []byte) {
	if hitl == nil || len(raw) == 0 {
		return
	}
	var env struct {
		MsgType  string         `json:"msg_type"`
		DeviceID string         `json:"device_id"`
		Payload  map[string]any `json:"payload"`
	}
	if err := json.Unmarshal(raw, &env); err != nil {
		return
	}
	p := env.Payload
	if p == nil {
		return
	}

	switch msgType {
	case "HITL_REQ":
		captureHitlReq(hitl, fromDevice, p)
	case "HITL_RES":
		captureHitlRes(hitl, p)
	}
}

func captureHitlReq(hitl *store.HitlPendingStore, fromAgent string, p map[string]any) {
	taskID, _ := p["task_id"].(string)
	if taskID == "" {
		return
	}
	userID, _ := p["target_user_id"].(string)
	if userID == "" {
		userID, _ = p["user_id"].(string)
	}
	if userID == "" {
		return
	}
	agentID, _ := p["agent_id"].(string)
	if agentID == "" {
		agentID = fromAgent
	}
	threadID, _ := p["thread_id"].(string)
	desc, _ := p["description"].(string)
	tool, _ := p["tool"].(string)
	risk, _ := p["risk_level"].(string)
	if risk == "" {
		risk = "critical"
	}
	entry := &store.HitlPending{
		TaskID:      taskID,
		UserID:      userID,
		AgentID:     agentID,
		ThreadID:    threadID,
		Description: desc,
		Tool:        tool,
		RiskLevel:   risk,
		Status:      "pending",
	}
	if err := hitl.UpsertPending(entry); err != nil {
		log.Printf("[HITL] capture REQ: %v", err)
	}
}

func captureHitlRes(hitl *store.HitlPendingStore, p map[string]any) {
	taskID, _ := p["task_id"].(string)
	if taskID == "" {
		return
	}
	decision, _ := p["decision"].(string)
	status := "resolved"
	if decision == "rejected" {
		status = "rejected"
	}
	if err := hitl.Resolve(taskID, status); err != nil {
		log.Printf("[HITL] capture RES: %v", err)
	}
}
