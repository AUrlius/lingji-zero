package handler

import (
	"encoding/json"
	"log"
	"net/http"
	"sync"
	"time"
)

// Run 表示一次进化运行
type Run struct {
	RunID     string         `json:"run_id"`
	GenomeID  string         `json:"genome_id"`
	ParentID  string         `json:"parent_id,omitempty"`
	Status    string         `json:"status"`
	CreatedAt string         `json:"created_at,omitempty"`
	Spec      map[string]any `json:"spec,omitempty"`
}

// RunEvent 表示一次运行事件（POST /v1/runs/{id}/events 的 body）
type RunEvent struct {
	RunID   string         `json:"run_id"`
	Type    string         `json:"type"`
	Message string         `json:"message"`
	TS      string         `json:"ts"`
	Payload map[string]any `json:"payload,omitempty"`
}

// RunRegistry H0 内存存储 + H1 WS 广播
type RunRegistry struct {
	mu     sync.RWMutex
	runs   map[string]Run
	events map[string][]RunEvent
	wsHub  *RunWSHub
}

// NewRunRegistry 创建 RunRegistry
func NewRunRegistry(wsHub *RunWSHub) *RunRegistry {
	return &RunRegistry{
		runs:   make(map[string]Run),
		events: make(map[string][]RunEvent),
		wsHub:  wsHub,
	}
}

// HandleHealth GET /v1/health
func (r *RunRegistry) HandleHealth(w http.ResponseWriter, req *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{
		"ok":          true,
		"service":     "lingji-gateway",
		"runregistry": "h1",
		"ws_url":      "ws://lingji.mygoal.tech:443/v1/ws/runs",
	})
}

// HandleCreateRun POST /v1/runs
func (r *RunRegistry) HandleCreateRun(w http.ResponseWriter, req *http.Request) {
	var body map[string]any
	if err := json.NewDecoder(req.Body).Decode(&body); err != nil {
		http.Error(w, `{"error":"bad_request"}`, http.StatusBadRequest)
		return
	}

	runID, _ := body["run_id"].(string)
	if runID == "" {
		http.Error(w, `{"error":"missing run_id"}`, http.StatusBadRequest)
		return
	}

	genomeID, _ := body["genome_id"].(string)
	parentID, _ := body["parent_id"].(string)
	status, _ := body["status"].(string)
	if status == "" {
		status = "pending"
	}
	createdAt, _ := body["created_at"].(string)
	spec, _ := body["spec"].(map[string]any)

	r.mu.Lock()
	_, exists := r.runs[runID]
	r.runs[runID] = Run{
		RunID:     runID,
		GenomeID:  genomeID,
		ParentID:  parentID,
		Status:    status,
		CreatedAt: createdAt,
		Spec:      spec,
	}
	if r.events[runID] == nil {
		r.events[runID] = make([]RunEvent, 0)
	}
	r.mu.Unlock()

	code := http.StatusCreated
	if exists {
		code = http.StatusOK
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]any{
		"run_id": runID,
		"status": status,
	})
}

// HandleGetRun GET /v1/runs/{run_id}
func (r *RunRegistry) HandleGetRun(w http.ResponseWriter, req *http.Request) {
	runID := req.PathValue("run_id")

	r.mu.RLock()
	run, ok := r.runs[runID]
	events := r.events[runID]
	r.mu.RUnlock()

	if !ok {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		json.NewEncoder(w).Encode(map[string]any{"error": "not_found"})
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]any{
		"run_id":        run.RunID,
		"genome_id":     run.GenomeID,
		"parent_id":     run.ParentID,
		"status":        run.Status,
		"created_at":    run.CreatedAt,
		"spec":          run.Spec,
		"events_count":  len(events),
	})
}

// HandlePostEvent POST /v1/runs/{run_id}/events
func (r *RunRegistry) HandlePostEvent(w http.ResponseWriter, req *http.Request) {
	runID := req.PathValue("run_id")

	var event RunEvent
	if err := json.NewDecoder(req.Body).Decode(&event); err != nil {
		http.Error(w, `{"error":"bad_request"}`, http.StatusBadRequest)
		return
	}

	if event.TS == "" {
		event.TS = time.Now().UTC().Format(time.RFC3339)
	}
	if event.RunID == "" {
		event.RunID = runID
	}

	r.mu.Lock()
	r.events[runID] = append(r.events[runID], event)

	// 更新 Run 状态（若 event payload 含 status）
	if status, ok := event.Payload["status"].(string); ok {
		if run, exists := r.runs[runID]; exists {
			run.Status = status
			r.runs[runID] = run
		}
	}
	r.mu.Unlock()

	// 广播到 H1 WebSocket 客户端
	if r.wsHub != nil {
		r.wsHub.Broadcast(event)
	}

	log.Printf("[RunRegistry] 事件已记录: run=%s type=%s", runID, event.Type)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)
	json.NewEncoder(w).Encode(map[string]any{"accepted": true})
}
