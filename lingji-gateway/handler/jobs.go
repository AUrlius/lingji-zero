package handler

import (
	"encoding/json"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/hub"
	"github.com/AUrlius/lingji-gateway/protocol"
	"github.com/AUrlius/lingji-gateway/queue"
	"github.com/AUrlius/lingji-gateway/store"
)

// JobsHandler serves Fleet 4.0a/4.0d-2 job API.
type JobsHandler struct {
	config *config.Config
	jobs   *store.JobStore
	hub    *hub.Hub
	queue  *queue.OfflineQueue
}

func NewJobsHandler(cfg *config.Config, jobs *store.JobStore) *JobsHandler {
	return &JobsHandler{config: cfg, jobs: jobs}
}

func (h *JobsHandler) WithHub(hub *hub.Hub, q *queue.OfflineQueue) *JobsHandler {
	h.hub = hub
	h.queue = q
	return h
}

func (h *JobsHandler) authOK(r *http.Request) bool {
	if h.config.AuthToken == "" {
		return true
	}
	if auth := r.Header.Get("Authorization"); auth == "Bearer "+h.config.AuthToken {
		return true
	}
	return r.URL.Query().Get("token") == h.config.AuthToken
}

type createJobRequest struct {
	UserID           string         `json:"user_id"`
	SchedulerAgentID string         `json:"scheduler_agent_id"`
	Intent           string         `json:"intent"`
	Playbook         string         `json:"playbook"`
	Plan             map[string]any `json:"plan"`
	ApprovalScope    map[string]any `json:"approval_scope"`
}

// HandleCreate POST /v1/jobs
func (h *JobsHandler) HandleCreate(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	var req createJobRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	if req.UserID == "" {
		http.Error(w, "user_id required", http.StatusBadRequest)
		return
	}
	if req.Playbook == "" {
		req.Playbook = "fleet.file_transfer"
	}
	job, err := h.jobs.CreateJob(store.CreateJobInput{
		UserID:           req.UserID,
		SchedulerAgentID: req.SchedulerAgentID,
		Intent:           req.Intent,
		Playbook:         req.Playbook,
		Plan:             req.Plan,
		ApprovalScope:    req.ApprovalScope,
	})
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	h.pushJobProgress(job)
	writeJSON(w, http.StatusCreated, job)
}

// HandleList GET /v1/jobs?user_id=
func (h *JobsHandler) HandleList(w http.ResponseWriter, r *http.Request) {
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
		http.Error(w, "user_id required", http.StatusBadRequest)
		return
	}
	limit := 30
	if s := r.URL.Query().Get("limit"); s != "" {
		if n, err := strconv.Atoi(s); err == nil && n > 0 {
			limit = n
		}
	}
	items, err := h.jobs.ListJobs(userID, limit)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	if items == nil {
		items = []*store.Job{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"jobs": items, "user_id": userID})
}

// HandleGet GET /v1/jobs/{job_id}
func (h *JobsHandler) HandleGet(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	jobID := r.PathValue("job_id")
	if jobID == "" {
		jobID = strings.TrimPrefix(r.URL.Path, "/v1/jobs/")
		if i := strings.IndexByte(jobID, '/'); i >= 0 {
			jobID = jobID[:i]
		}
	}
	if jobID == "" {
		http.Error(w, "job_id required", http.StatusBadRequest)
		return
	}
	job, err := h.jobs.GetJob(jobID)
	if err != nil {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	writeJSON(w, http.StatusOK, job)
}

type reportStepRequest struct {
	Status   string         `json:"status"`
	Evidence map[string]any `json:"evidence"`
	Error    string         `json:"error"`
}

// HandleReport POST /v1/jobs/{job_id}/steps/{step_id}/report
func (h *JobsHandler) HandleReport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	jobID := r.PathValue("job_id")
	stepID := r.PathValue("step_id")
	if jobID == "" {
		rest := strings.TrimPrefix(r.URL.Path, "/v1/jobs/")
		parts := strings.Split(rest, "/")
		if len(parts) >= 1 {
			jobID = parts[0]
		}
		if len(parts) >= 3 {
			stepID = parts[2]
		}
	}
	var req reportStepRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	job, err := h.jobs.ReportStep(jobID, stepID, store.ReportStepInput{
		Status:   req.Status,
		Evidence: req.Evidence,
		Error:    req.Error,
	})
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	h.pushJobProgress(job)
	writeJSON(w, http.StatusOK, job)
}

type dispatchRequest struct {
	StepID     string `json:"step_id"`
	ExecutorID string `json:"executor_id"`
}

// HandleDispatch POST /v1/jobs/{job_id}/dispatch — mark step dispatched and send JOB_DELEGATE.
func (h *JobsHandler) HandleDispatch(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	jobID := r.PathValue("job_id")
	if jobID == "" {
		rest := strings.TrimPrefix(r.URL.Path, "/v1/jobs/")
		if i := strings.IndexByte(rest, '/'); i >= 0 {
			jobID = rest[:i]
		} else {
			jobID = rest
		}
	}
	var req dispatchRequest
	_ = json.NewDecoder(r.Body).Decode(&req)
	job, err := h.jobs.DispatchStep(jobID, req.StepID, req.ExecutorID)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	h.sendDelegate(job, req.StepID, req.ExecutorID)
	h.pushJobProgress(job)
	writeJSON(w, http.StatusOK, job)
}

func (h *JobsHandler) sendDelegate(job *store.Job, stepID, executorHint string) {
	if h.hub == nil || job == nil {
		return
	}
	executor := executorHint
	var step *store.JobStep
	for i := range job.Steps {
		st := &job.Steps[i]
		if stepID != "" && st.StepID != stepID {
			continue
		}
		if st.Status == "dispatched" || st.Status == "running" {
			step = st
			if executor == "" {
				executor = st.ExecutorID
			}
			break
		}
	}
	if step == nil {
		return
	}
	if executor == "" {
		executor = step.ExecutorID
	}
	if executor == "" {
		executor = "lingji-pc"
	}
	msg := protocol.NewMessage(protocol.MsgJobDelegate, "gateway", map[string]any{
		"job_id":             job.JobID,
		"step_id":            step.StepID,
		"playbook_id":        job.Playbook,
		"approval_scope":     job.ApprovalScope,
		"user_id":            job.UserID,
		"scheduler_agent_id": job.SchedulerAgentID,
		"executor_id":        executor,
		"intent":             job.Intent,
	})
	raw, err := msg.ToJSON()
	if err != nil {
		log.Printf("[JOB] encode DELEGATE: %v", err)
		return
	}
	if !h.hub.SendToDevice(executor, []byte(raw)) {
		log.Printf("[JOB] executor %s 不在线，DELEGATE 入离线队列 job=%s", executor, job.JobID)
		if h.queue != nil {
			h.queue.Enqueue(executor, raw)
		}
	}
}

func (h *JobsHandler) pushJobProgress(job *store.Job) {
	if h.hub == nil || job == nil || job.UserID == "" {
		return
	}
	b, err := json.Marshal(job)
	if err != nil {
		return
	}
	var jobMap map[string]any
	if err := json.Unmarshal(b, &jobMap); err != nil {
		return
	}
	text := job.Summary
	if text == "" {
		text = job.JobID + " " + job.Status
	}
	msg := protocol.NewMessage(protocol.MsgAgentRes, "gateway", map[string]any{
		"text":           text,
		"status":         "job_progress",
		"job_id":         job.JobID,
		"job":            jobMap,
		"target_user_id": job.UserID,
	})
	raw, err := msg.ToJSON()
	if err != nil {
		return
	}
	DeliverDownstream(h.hub, h.queue, []byte(raw))
}

// StartStaleWatcher fails dispatched steps with no REPORT (default 30m).
func (h *JobsHandler) StartStaleWatcher(timeout time.Duration) {
	if timeout <= 0 {
		timeout = 30 * time.Minute
	}
	go func() {
		t := time.NewTicker(30 * time.Second)
		defer t.Stop()
		for range t.C {
			jobs, err := h.jobs.FailStaleDispatched(timeout)
			if err != nil || len(jobs) == 0 {
				continue
			}
			for _, j := range jobs {
				h.pushJobProgress(j)
			}
		}
	}()
}
