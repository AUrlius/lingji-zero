package handler

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/AUrlius/lingji-gateway/store"
)

// JobsHandler serves Fleet 4.0a job API.
type JobsHandler struct {
	config *config.Config
	jobs   *store.JobStore
}

func NewJobsHandler(cfg *config.Config, jobs *store.JobStore) *JobsHandler {
	return &JobsHandler{config: cfg, jobs: jobs}
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
	})
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	writeJSON(w, http.StatusCreated, job)
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
	jobID := strings.TrimPrefix(r.URL.Path, "/v1/jobs/")
	if jobID == "" || jobID == r.URL.Path {
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
