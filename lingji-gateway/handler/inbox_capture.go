package handler

import (
	"encoding/json"
	"log"
	"strings"

	"github.com/AUrlius/lingji-gateway/store"
)

// CaptureWSMessage persists Fleet Phase 2 inbox rows from WS traffic.
func CaptureWSMessage(inbox *store.InboxStore, msgType string, fromDevice string, raw []byte) {
	if inbox == nil || len(raw) == 0 {
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
		p = map[string]any{}
	}

	switch msgType {
	case "CMD_TEXT":
		captureCmdText(inbox, fromDevice, p)
	case "AGENT_RES":
		captureAgentRes(inbox, fromDevice, p)
	case "FLEET_ACK":
		captureFleetAck(inbox, fromDevice, p)
	}
}

// CaptureFleetTransfer records a completed fleet file relay in the inbox.
func CaptureFleetTransfer(inbox *store.InboxStore, threadID, userID, agentID, summary string) {
	if inbox == nil || summary == "" || userID == "" {
		return
	}
	if threadID == "" {
		threadID = "fleet-" + userID
		_ = inbox.UpsertThread(threadID, userID, agentID, "Fleet 传输")
	}
	if err := inbox.AppendMessage(threadID, userID, agentID, "agent", summary, "fleet"); err != nil {
		log.Printf("[Inbox] fleet capture: %v", err)
	}
}

func captureFleetAck(inbox *store.InboxStore, fromDevice string, p map[string]any) {
	// ACK completion is captured in FleetHandler.HandleAck via CaptureFleetTransfer.
	_ = fromDevice
	_ = p
}

func captureCmdText(inbox *store.InboxStore, fromDevice string, p map[string]any) {
	text, _ := p["text"].(string)
	threadID, _ := p["thread_id"].(string)
	userID, _ := p["user_id"].(string)
	if userID == "" {
		userID = fromDevice
	}
	agentID := resolveTargetAgentIDFromPayload(p)
	source, _ := p["source"].(string)
	if source == "" {
		source = "web"
	}
	if text == "" {
		if uploadLine := summarizeUploads(p); uploadLine != "" && threadID != "" {
			if err := inbox.AppendMessage(threadID, userID, agentID, "user", uploadLine, source); err != nil {
				log.Printf("[Inbox] CMD_TEXT upload capture: %v", err)
			}
			return
		}
		if threadID != "" {
			_ = inbox.UpsertThread(threadID, userID, agentID, "")
		}
		return
	}
	if err := inbox.AppendMessage(threadID, userID, agentID, "user", text, source); err != nil {
		log.Printf("[Inbox] CMD_TEXT capture: %v", err)
	}
}

func summarizeUploads(p map[string]any) string {
	raw, ok := p["uploads"].([]any)
	if !ok || len(raw) == 0 {
		return ""
	}
	names := make([]string, 0, len(raw))
	for _, item := range raw {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		name, _ := m["name"].(string)
		if name == "" {
			name, _ = m["file_id"].(string)
		}
		if name != "" {
			names = append(names, name)
		}
	}
	if len(names) == 0 {
		return "[上传文件]"
	}
	return "[上传文件] " + strings.Join(names, ", ")
}

func captureAgentRes(inbox *store.InboxStore, fromDevice string, p map[string]any) {
	status, _ := p["status"].(string)
	if status == "connected" || status == "rejected" {
		return
	}
	agentID := fromDevice
	if !IsAgentDevice(agentID) {
		if ta, ok := p["target_agent_id"].(string); ok && ta != "" {
			agentID = ta
		} else {
			agentID = DefaultAgentID
		}
	}
	userID, _ := p["target_user_id"].(string)
	if userID == "" {
		userID, _ = p["user_id"].(string)
	}
	threadID, _ := p["thread_id"].(string)

	if sessions, ok := p["sessions"].([]any); ok {
		for _, item := range sessions {
			m, ok := item.(map[string]any)
			if !ok {
				continue
			}
			tid, _ := m["thread_id"].(string)
			title, _ := m["title"].(string)
			aid, _ := m["agent_id"].(string)
			if aid == "" {
				aid = agentID
			}
			uid := userID
			if uid == "" {
				uid, _ = m["user_id"].(string)
			}
			if tid != "" && uid != "" {
				_ = inbox.UpsertThread(tid, uid, aid, title)
			}
		}
	}

	text, _ := p["text"].(string)
	if text == "" || status == "queued" {
		return
	}
	if userID == "" || threadID == "" {
		return
	}
	if err := inbox.AppendMessage(threadID, userID, agentID, "agent", text, "agent"); err != nil {
		log.Printf("[Inbox] AGENT_RES capture: %v", err)
	}
}

func resolveTargetAgentIDFromPayload(p map[string]any) string {
	if p == nil {
		return DefaultAgentID
	}
	if id, ok := p["target_agent_id"].(string); ok && id != "" {
		return id
	}
	return DefaultAgentID
}
