package handler

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/hub"
	"github.com/AUrlius/lingji-gateway/protocol"
	"github.com/AUrlius/lingji-gateway/queue"
	"github.com/AUrlius/lingji-gateway/store"
	"github.com/google/uuid"
)

type fleetTransferRequest struct {
	FromAgentID string           `json:"from_agent_id"`
	ToAgentID   string           `json:"to_agent_id"`
	ToUserID    string           `json:"to_user_id"`
	ThreadID    string           `json:"thread_id"`
	UserID      string           `json:"user_id"`
	JobID       string           `json:"job_id"`
	Uploads     []map[string]any `json:"uploads"`
}

type pendingTransfer struct {
	FromAgentID string
	ToAgentID   string
	UserID      string
	ThreadID    string
	JobID       string
	Uploads     []map[string]any
}

// FleetHandler orchestrates cross-agent file relay (Fleet Phase 3).
type FleetHandler struct {
	hub      *hub.Hub
	config   *config.Config
	queue    *queue.OfflineQueue
	inbox    *store.InboxStore
	registry *store.FileRegistryStore
	jobs     *store.JobStore
	pending  map[string]*pendingTransfer
	pendingMu sync.RWMutex
}

func NewFleetHandler(h *hub.Hub, cfg *config.Config, q *queue.OfflineQueue, inbox *store.InboxStore, registry *store.FileRegistryStore, jobs *store.JobStore) *FleetHandler {
	return &FleetHandler{
		hub:      h,
		config:   cfg,
		queue:    q,
		inbox:    inbox,
		registry: registry,
		jobs:     jobs,
		pending:  make(map[string]*pendingTransfer),
	}
}

func (f *FleetHandler) authOK(r *http.Request) bool {
	if f.config.AuthToken == "" {
		return true
	}
	if auth := r.Header.Get("Authorization"); auth == "Bearer "+f.config.AuthToken {
		return true
	}
	return r.URL.Query().Get("token") == f.config.AuthToken
}

func (f *FleetHandler) HandleTransfer(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !f.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	var req fleetTransferRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}

	if req.FromAgentID == "" || len(req.Uploads) == 0 {
		http.Error(w, "from_agent_id and uploads required", http.StatusBadRequest)
		return
	}
	if !IsAgentDevice(req.FromAgentID) {
		http.Error(w, "from_agent_id must be lingji-*", http.StatusBadRequest)
		return
	}
	toAgent := strings.TrimSpace(req.ToAgentID)
	toUser := strings.TrimSpace(req.ToUserID)
	if (toAgent == "" && toUser == "") || (toAgent != "" && toUser != "") {
		http.Error(w, "exactly one of to_agent_id or to_user_id required", http.StatusBadRequest)
		return
	}
	if toAgent != "" && !IsAgentDevice(toAgent) {
		http.Error(w, "to_agent_id must be lingji-*", http.StatusBadRequest)
		return
	}

	transferID := uuid.New().String()

	if toUser != "" {
		summary, attachments := f.buildUserDelivery(req.FromAgentID, toUser, req.Uploads)
		reply := protocol.NewMessage(protocol.MsgAgentRes, req.FromAgentID, map[string]any{
			"text":             summary,
			"target_user_id":   toUser,
			"thread_id":        req.ThreadID,
			"transfer_id":      transferID,
			"fleet_status":     "delivered",
			"attachments":      attachments,
		})
		raw, err := reply.ToJSON()
		if err != nil {
			http.Error(w, "encode failed", http.StatusInternalServerError)
			return
		}
		DeliverDownstream(f.hub, f.queue, []byte(raw))
		CaptureFleetTransfer(f.inbox, req.ThreadID, toUser, req.FromAgentID, summary)
	writeJSON(w, http.StatusOK, map[string]any{
			"transfer_id": transferID,
			"status":      "delivered",
			"to_user_id":  toUser,
		})
		return
	}

	f.pendingMu.Lock()
	f.pending[transferID] = &pendingTransfer{
		FromAgentID: req.FromAgentID,
		ToAgentID:   toAgent,
		UserID:      req.UserID,
		ThreadID:    req.ThreadID,
		JobID:       strings.TrimSpace(req.JobID),
		Uploads:     req.Uploads,
	}
	f.pendingMu.Unlock()

	if f.jobs != nil && req.JobID != "" {
		_ = f.jobs.LinkTransfer(transferID, req.JobID, req.JobID+"-S3")
		_ = f.jobs.OnTransferStarted(req.JobID, transferID)
	}

	deliver := protocol.NewMessage(protocol.MsgFleetDeliver, "gateway", map[string]any{
		"transfer_id":   transferID,
		"from_agent_id": req.FromAgentID,
		"to_agent_id":   toAgent,
		"thread_id":     req.ThreadID,
		"user_id":       req.UserID,
		"uploads":       req.Uploads,
	})
	raw, err := deliver.ToJSON()
	if err != nil {
		http.Error(w, "encode failed", http.StatusInternalServerError)
		return
	}

	status := "pending"
	if !f.hub.SendToDevice(toAgent, []byte(raw)) {
		log.Printf("[Fleet] Agent %s 不在线，FLEET_DELIVER 入离线队列", toAgent)
		f.queue.Enqueue(toAgent, raw)
		status = "queued"
		if req.UserID != "" {
			queuedText := fmt.Sprintf("目标 Agent (%s) 当前不在线，文件传输已排队，上线后自动投递。", toAgent)
			notify := protocol.NewMessage(protocol.MsgAgentRes, "gateway", map[string]any{
				"text":           queuedText,
				"status":         "queued",
				"target_user_id": req.UserID,
				"thread_id":      req.ThreadID,
				"transfer_id":    transferID,
				"fleet_status":   "queued",
			})
			if data, err := notify.ToJSON(); err == nil {
				DeliverDownstream(f.hub, f.queue, []byte(data))
			}
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"transfer_id":  transferID,
		"status":       status,
		"to_agent_id":  toAgent,
		"job_id":       strings.TrimSpace(req.JobID),
	})
}

func (f *FleetHandler) HandleAck(fromDevice string, raw []byte) {
	msg, err := protocol.ParseMessage(string(raw))
	if err != nil {
		log.Printf("[Fleet] FLEET_ACK 解析失败: %v", err)
		return
	}
	p := msg.Payload
	transferID, _ := p["transfer_id"].(string)
	status, _ := p["status"].(string)
	if status == "" {
		status = "error"
	}

	f.pendingMu.Lock()
	pt, ok := f.pending[transferID]
	if ok {
		delete(f.pending, transferID)
	}
	f.pendingMu.Unlock()

	fromAgent := fromDevice
	toAgent := ""
	userID := ""
	threadID := ""
	var uploads []map[string]any
	if pt != nil {
		fromAgent = pt.FromAgentID
		toAgent = pt.ToAgentID
		userID = pt.UserID
		threadID = pt.ThreadID
		uploads = pt.Uploads
	} else {
		fromAgent, _ = p["from_agent_id"].(string)
		toAgent, _ = p["to_agent_id"].(string)
		userID, _ = p["user_id"].(string)
		threadID, _ = p["thread_id"].(string)
		if rawUploads, ok := p["uploads"].([]any); ok {
			for _, item := range rawUploads {
				if m, ok := item.(map[string]any); ok {
					uploads = append(uploads, m)
				}
			}
		}
	}

	summary := f.buildAckSummary(fromAgent, toAgent, status, p, uploads)
	if userID != "" {
		reply := protocol.NewMessage(protocol.MsgAgentRes, fromDevice, map[string]any{
			"text":           summary,
			"target_user_id": userID,
			"thread_id":      threadID,
			"transfer_id":    transferID,
			"fleet_status":   status,
		})
		if data, err := reply.ToJSON(); err == nil {
			DeliverDownstream(f.hub, f.queue, []byte(data))
		}
	}

	if fromAgent != "" && fromAgent != fromDevice {
		notify := protocol.NewMessage(protocol.MsgAgentRes, "gateway", map[string]any{
			"text":         summary,
			"transfer_id":  transferID,
			"fleet_status": status,
		})
		if data, err := notify.ToJSON(); err == nil {
			f.hub.SendToDevice(fromAgent, []byte(data))
		}
	}

	agentID := fromAgent
	if agentID == "" {
		agentID = fromDevice
	}
	CaptureFleetTransfer(f.inbox, threadID, userID, agentID, summary)

	if f.jobs != nil && transferID != "" {
		evidence := map[string]any{
			"transfer_id": transferID,
			"status":      status,
		}
		if saved, ok := p["saved"].([]any); ok {
			evidence["saved"] = saved
		}
		if job, jobSummary, err := f.jobs.OnTransferAck(transferID, status, evidence); err == nil && jobSummary != "" && userID != "" {
			jobReply := protocol.NewMessage(protocol.MsgAgentRes, "gateway", map[string]any{
				"text":           jobSummary,
				"target_user_id": userID,
				"thread_id":      threadID,
				"job_id":         job.JobID,
				"job_status":     job.Status,
			})
			if data, err := jobReply.ToJSON(); err == nil {
				DeliverDownstream(f.hub, f.queue, []byte(data))
			}
		}
	}
}

func (f *FleetHandler) buildUserDelivery(fromAgent, toUser string, uploads []map[string]any) (string, []map[string]any) {
	names := make([]string, 0, len(uploads))
	attachments := make([]map[string]any, 0, len(uploads))
	for _, u := range uploads {
		name, _ := u["name"].(string)
		if name == "" {
			name, _ = u["file_id"].(string)
		}
		names = append(names, name)
		attachments = append(attachments, u)
	}
	summary := fmt.Sprintf("📁 Fleet: %s %s → %s 已推送", strings.Join(names, ", "), fromAgent, toUser)
	return summary, attachments
}

func (f *FleetHandler) buildAckSummary(fromAgent, toAgent, status string, p map[string]any, uploads []map[string]any) string {
	if status == "ok" {
		names := make([]string, 0)
		if saved, ok := p["saved"].([]any); ok {
			for _, item := range saved {
				if m, ok := item.(map[string]any); ok {
					if n, ok := m["name"].(string); ok {
						names = append(names, n)
					}
				}
			}
		}
		if len(names) == 0 {
			for _, u := range uploads {
				if n, ok := u["name"].(string); ok {
					names = append(names, n)
				}
			}
		}
		label := strings.Join(names, ", ")
		if label == "" {
			label = "文件"
		}
		lfSuffix := ""
		if saved, ok := p["saved"].([]any); ok {
			for _, item := range saved {
				if m, ok := item.(map[string]any); ok {
					if lf, ok := m["lingji_file_id"].(string); ok && lf != "" {
						lfSuffix = " · " + lf
						break
					}
				}
			}
		}
		if lfSuffix == "" {
			if lfs, ok := p["lingji_files"].([]any); ok && len(lfs) > 0 {
				if m, ok := lfs[0].(map[string]any); ok {
					if lf, ok := m["lingji_file_id"].(string); ok && lf != "" {
						lfSuffix = " · " + lf
					}
				}
			}
		}
		return fmt.Sprintf("📁 Fleet: %s %s → %s 已保存%s", label, fromAgent, toAgent, lfSuffix)
	}
	errText, _ := p["error"].(string)
	if errText == "" {
		errText = "传输失败"
	}
	return fmt.Sprintf("📁 Fleet: %s → %s 失败 (%s)", fromAgent, toAgent, errText)
}

type fleetRelayRequest struct {
	LingjiFileID string `json:"lingji_file_id"`
	UserID       string `json:"user_id"`
	FromAgentID  string `json:"from_agent_id"`
	ToAgentID    string `json:"to_agent_id"`
	ToUserID     string `json:"to_user_id"`
	ThreadID     string `json:"thread_id"`
}

func (f *FleetHandler) HandleRelay(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !f.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	if f.registry == nil {
		http.Error(w, "registry unavailable", http.StatusServiceUnavailable)
		return
	}
	var req fleetRelayRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	toAgent := strings.TrimSpace(req.ToAgentID)
	toUser := strings.TrimSpace(req.ToUserID)
	if req.LingjiFileID == "" || req.UserID == "" {
		http.Error(w, "lingji_file_id and user_id required", http.StatusBadRequest)
		return
	}
	if (toAgent == "" && toUser == "") || (toAgent != "" && toUser != "") {
		http.Error(w, "exactly one of to_agent_id or to_user_id required", http.StatusBadRequest)
		return
	}
	lf, err := f.registry.Get(req.UserID, req.LingjiFileID)
	if err != nil || lf == nil {
		http.Error(w, "file not found", http.StatusNotFound)
		return
	}
	holder := lf.HolderAgentID
	if holder == "" {
		http.Error(w, "file has no holder", http.StatusBadRequest)
		return
	}
	relay := protocol.NewMessage(protocol.MsgFleetRelayByID, "gateway", map[string]any{
		"lingji_file_id": req.LingjiFileID,
		"user_id":        req.UserID,
		"from_agent_id":  req.FromAgentID,
		"to_agent_id":    toAgent,
		"to_user_id":     toUser,
		"thread_id":      req.ThreadID,
		"local_path":     lf.LocalPath,
		"name":           lf.Name,
	})
	raw, err := relay.ToJSON()
	if err != nil {
		http.Error(w, "encode failed", http.StatusInternalServerError)
		return
	}
	status := "pending"
	if !f.hub.SendToDevice(holder, []byte(raw)) {
		f.queue.Enqueue(holder, raw)
		status = "queued"
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status":          status,
		"lingji_file_id":  req.LingjiFileID,
		"holder_agent_id": holder,
	})
}

// DeliverDownstream fans out AGENT_RES / HITL_REQ to target_user_id or target_device_id.
func DeliverDownstream(h *hub.Hub, q *queue.OfflineQueue, raw []byte) {
	msg, err := protocol.ParseMessage(string(raw))
	if err != nil {
		log.Printf("[Route] 下行消息解析失败，fallback 广播: %v", err)
		h.BroadcastToAll(raw, DefaultAgentID)
		return
	}

	targetUser, _ := msg.Payload["target_user_id"].(string)
	if targetUser != "" {
		if n := h.SendToUser(targetUser, raw); n > 0 {
			return
		}
		log.Printf("[Route] 用户 %s 无在线连接，入离线队列", targetUser)
		q.Enqueue(targetUser, string(raw))
		return
	}

	target, _ := msg.Payload["target_device_id"].(string)
	if target != "" && target != DefaultAgentID {
		if h.SendToDevice(target, raw) {
			return
		}
		log.Printf("[Route] 定向投递失败，入离线队列: %s", target)
		q.Enqueue(target, string(raw))
		return
	}

	h.BroadcastToAll(raw, DefaultAgentID)
}
