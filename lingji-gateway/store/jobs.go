package store

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// Job is a user-visible Fleet task (L1).
type Job struct {
	JobID             string         `json:"job_id"`
	UserID            string         `json:"user_id"`
	SchedulerAgentID  string         `json:"scheduler_agent_id"`
	Intent            string         `json:"intent"`
	Playbook          string         `json:"playbook"`
	Status            string         `json:"status"`
	Plan              map[string]any `json:"plan,omitempty"`
	Summary           string         `json:"summary,omitempty"`
	CreatedAt         string         `json:"created_at"`
	UpdatedAt         string         `json:"updated_at"`
	ClosedAt          string         `json:"closed_at,omitempty"`
	Steps             []JobStep      `json:"steps,omitempty"`
	TransferIDs       []string         `json:"transfer_ids,omitempty"`
	ApprovalScope     map[string]any   `json:"approval_scope,omitempty"`
}

// JobStep is an L2 delegated step.
type JobStep struct {
	StepID     string         `json:"step_id"`
	JobID      string         `json:"job_id"`
	Name       string         `json:"name"`
	ExecutorID string         `json:"executor_id,omitempty"`
	Status     string         `json:"status"`
	Mandatory  bool           `json:"mandatory"`
	Evidence   map[string]any `json:"evidence,omitempty"`
	Error      string         `json:"error,omitempty"`
	SortOrder  int            `json:"sort_order"`
	StartedAt  string         `json:"started_at,omitempty"`
	CompletedAt string        `json:"completed_at,omitempty"`
}

// JobStore persists LJ-* jobs (same SQLite as inbox).
type JobStore struct {
	db *sql.DB
}

// NewJobStoreFromDB reuses an existing inbox database handle.
func NewJobStoreFromDB(db *sql.DB) (*JobStore, error) {
	s := &JobStore{db: db}
	if err := s.migrate(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *JobStore) migrate() error {
	_, err := s.db.Exec(`
		CREATE TABLE IF NOT EXISTS fleet_jobs (
			job_id TEXT PRIMARY KEY,
			user_id TEXT NOT NULL,
			scheduler_agent_id TEXT NOT NULL DEFAULT '',
			intent TEXT NOT NULL DEFAULT '',
			playbook TEXT NOT NULL DEFAULT '',
			status TEXT NOT NULL DEFAULT 'created',
			plan_json TEXT NOT NULL DEFAULT '{}',
			summary TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL,
			closed_at TEXT NOT NULL DEFAULT '',
			approval_scope_json TEXT NOT NULL DEFAULT '{}'
		);
		CREATE INDEX IF NOT EXISTS idx_fleet_jobs_user
			ON fleet_jobs(user_id, updated_at DESC);

		CREATE TABLE IF NOT EXISTS fleet_job_steps (
			step_id TEXT PRIMARY KEY,
			job_id TEXT NOT NULL,
			name TEXT NOT NULL,
			executor_id TEXT NOT NULL DEFAULT '',
			status TEXT NOT NULL DEFAULT 'pending',
			mandatory INTEGER NOT NULL DEFAULT 1,
			evidence_json TEXT NOT NULL DEFAULT '{}',
			error_text TEXT NOT NULL DEFAULT '',
			sort_order INTEGER NOT NULL DEFAULT 0,
			started_at TEXT NOT NULL DEFAULT '',
			completed_at TEXT NOT NULL DEFAULT '',
			FOREIGN KEY (job_id) REFERENCES fleet_jobs(job_id)
		);
		CREATE INDEX IF NOT EXISTS idx_fleet_job_steps_job
			ON fleet_job_steps(job_id, sort_order);

		CREATE TABLE IF NOT EXISTS fleet_job_transfers (
			transfer_id TEXT PRIMARY KEY,
			job_id TEXT NOT NULL,
			step_id TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL
		);
	`)
	if err != nil {
		return err
	}
	return s.ensureApprovalScopeColumn()
}

func (s *JobStore) ensureApprovalScopeColumn() error {
	var n int
	err := s.db.QueryRow(
		`SELECT COUNT(*) FROM pragma_table_info('fleet_jobs') WHERE name='approval_scope_json'`,
	).Scan(&n)
	if err != nil {
		return err
	}
	if n > 0 {
		return nil
	}
	_, err = s.db.Exec(
		`ALTER TABLE fleet_jobs ADD COLUMN approval_scope_json TEXT NOT NULL DEFAULT '{}'`,
	)
	return err
}

// MintJobID returns LJ-XXXXXXXX style id.
func MintJobID() (string, error) {
	b := make([]byte, 4)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return "LJ-" + strings.ToUpper(hex.EncodeToString(b)), nil
}

type CreateJobInput struct {
	UserID           string
	SchedulerAgentID string
	Intent           string
	Playbook         string
	Plan             map[string]any
	ApprovalScope    map[string]any
}

func DefaultApprovalScope(playbook string) map[string]any {
	if playbook == "" {
		playbook = "fleet.file_transfer"
	}
	return map[string]any{
		"expires_at":          time.Now().UTC().Add(time.Hour).Format(time.RFC3339),
		"playbooks":           []any{playbook},
		"allowed_paths":       []any{"/mnt/e/LingjiPlan/LingjiZero"},
		"auto_approve_tier0":  true,
	}
}

// CreateJob mints LJ-* and playbook steps.
func (s *JobStore) CreateJob(in CreateJobInput) (*Job, error) {
	if in.UserID == "" {
		return nil, fmt.Errorf("user_id required")
	}
	jobID, err := MintJobID()
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC().Format(time.RFC3339)
	plan := in.Plan
	if plan == nil {
		plan = map[string]any{}
	}
	planJSON, _ := json.Marshal(plan)
	scope := in.ApprovalScope
	if len(scope) == 0 {
		scope = DefaultApprovalScope(in.Playbook)
	}
	scopeJSON, _ := json.Marshal(scope)
	steps := buildPlaybookSteps(jobID, in.Playbook, plan)

	tx, err := s.db.Begin()
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()

	_, err = tx.Exec(`
		INSERT INTO fleet_jobs (
			job_id, user_id, scheduler_agent_id, intent, playbook,
			status, plan_json, summary, created_at, updated_at, approval_scope_json
		) VALUES (?, ?, ?, ?, ?, 'planned', ?, '', ?, ?, ?)`,
		jobID, in.UserID, in.SchedulerAgentID, in.Intent, in.Playbook,
		string(planJSON), now, now, string(scopeJSON),
	)
	if err != nil {
		return nil, err
	}

	for _, st := range steps {
		ev, _ := json.Marshal(st.Evidence)
		_, err = tx.Exec(`
			INSERT INTO fleet_job_steps (
				step_id, job_id, name, executor_id, status, mandatory,
				evidence_json, error_text, sort_order, started_at, completed_at
			) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, '', '')`,
			st.StepID, st.JobID, st.Name, st.ExecutorID, st.Status,
			boolToInt(st.Mandatory), string(ev), st.SortOrder,
		)
		if err != nil {
			return nil, err
		}
	}

	// Auto-complete resolve_targets when plan has sender/receiver.
	if in.Playbook == "fleet.file_transfer" {
		sender, _ := plan["sender_agent_id"].(string)
		receiver, _ := plan["receiver_agent_id"].(string)
		if sender != "" && receiver != "" {
			stepID := jobID + "-S1"
			ev, _ := json.Marshal(map[string]any{
				"sender_agent_id":   sender,
				"receiver_agent_id": receiver,
			})
			_, err = tx.Exec(`
				UPDATE fleet_job_steps SET status='completed', evidence_json=?, completed_at=?
				WHERE step_id=?`,
				string(ev), now, stepID,
			)
			if err != nil {
				return nil, err
			}
		}
	}

	if err = tx.Commit(); err != nil {
		return nil, err
	}
	return s.GetJob(jobID)
}

func buildPlaybookSteps(jobID, playbook string, plan map[string]any) []JobStep {
	if playbook == "fleet.file_transfer" {
		sender, _ := plan["sender_agent_id"].(string)
		receiver, _ := plan["receiver_agent_id"].(string)
		return []JobStep{
			{StepID: jobID + "-S1", JobID: jobID, Name: "resolve_targets", Status: "pending", Mandatory: true, SortOrder: 1},
			{StepID: jobID + "-S2", JobID: jobID, Name: "locate_and_upload", ExecutorID: sender, Status: "pending", Mandatory: true, SortOrder: 2},
			{StepID: jobID + "-S3", JobID: jobID, Name: "relay_deliver", ExecutorID: sender, Status: "pending", Mandatory: true, SortOrder: 3},
			{StepID: jobID + "-S4", JobID: jobID, Name: "receive_machine", ExecutorID: receiver, Status: "pending", Mandatory: true, SortOrder: 4},
		}
	}
	executor, _ := plan["executor_id"].(string)
	if executor == "" {
		executor = "lingji-pc"
	}
	name := "run_playbook"
	if strings.HasPrefix(playbook, "coding.") {
		name = "coding_run"
	}
	return []JobStep{
		{
			StepID:     jobID + "-S1",
			JobID:      jobID,
			Name:       name,
			ExecutorID: executor,
			Status:     "pending",
			Mandatory:  true,
			SortOrder:  1,
		},
	}
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

// GetJob loads job + steps + transfer ids.
func (s *JobStore) GetJob(jobID string) (*Job, error) {
	row := s.db.QueryRow(`
		SELECT job_id, user_id, scheduler_agent_id, intent, playbook, status,
		       plan_json, summary, created_at, updated_at, closed_at, approval_scope_json
		FROM fleet_jobs WHERE job_id=?`, jobID,
	)
	var j Job
	var planJSON string
	var closedAt string
	var scopeJSON string
	err := row.Scan(
		&j.JobID, &j.UserID, &j.SchedulerAgentID, &j.Intent, &j.Playbook, &j.Status,
		&planJSON, &j.Summary, &j.CreatedAt, &j.UpdatedAt, &closedAt, &scopeJSON,
	)
	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("job not found")
	}
	if err != nil {
		return nil, err
	}
	j.ClosedAt = closedAt
	_ = json.Unmarshal([]byte(planJSON), &j.Plan)
	if scopeJSON != "" && scopeJSON != "{}" {
		_ = json.Unmarshal([]byte(scopeJSON), &j.ApprovalScope)
	}

	steps, err := s.listSteps(jobID)
	if err != nil {
		return nil, err
	}
	j.Steps = steps

	rows, err := s.db.Query(
		`SELECT transfer_id FROM fleet_job_transfers WHERE job_id=? ORDER BY created_at`,
		jobID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var tid string
		if err := rows.Scan(&tid); err != nil {
			return nil, err
		}
		j.TransferIDs = append(j.TransferIDs, tid)
	}
	return &j, nil
}

func (s *JobStore) listSteps(jobID string) ([]JobStep, error) {
	rows, err := s.db.Query(`
		SELECT step_id, job_id, name, executor_id, status, mandatory,
		       evidence_json, error_text, sort_order, started_at, completed_at
		FROM fleet_job_steps WHERE job_id=? ORDER BY sort_order`, jobID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []JobStep
	for rows.Next() {
		var st JobStep
		var evJSON string
		var mandatory int
		if err := rows.Scan(
			&st.StepID, &st.JobID, &st.Name, &st.ExecutorID, &st.Status, &mandatory,
			&evJSON, &st.Error, &st.SortOrder, &st.StartedAt, &st.CompletedAt,
		); err != nil {
			return nil, err
		}
		st.Mandatory = mandatory != 0
		_ = json.Unmarshal([]byte(evJSON), &st.Evidence)
		out = append(out, st)
	}
	return out, nil
}

// LinkTransfer associates a fleet transfer with a job step.
func (s *JobStore) LinkTransfer(transferID, jobID, stepID string) error {
	if transferID == "" || jobID == "" {
		return fmt.Errorf("transfer_id and job_id required")
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, err := s.db.Exec(`
		INSERT INTO fleet_job_transfers (transfer_id, job_id, step_id, created_at)
		VALUES (?, ?, ?, ?)
		ON CONFLICT(transfer_id) DO UPDATE SET job_id=excluded.job_id, step_id=excluded.step_id`,
		transferID, jobID, stepID, now,
	)
	return err
}

// OnTransferStarted marks upload/relay steps completed when transfer is dispatched.
func (s *JobStore) OnTransferStarted(jobID, transferID string) error {
	if jobID == "" {
		return nil
	}
	now := time.Now().UTC().Format(time.RFC3339)
	ev, _ := json.Marshal(map[string]any{"transfer_id": transferID})
	for _, stepID := range []string{jobID + "-S2", jobID + "-S3"} {
		_, err := s.db.Exec(`
			UPDATE fleet_job_steps SET status='completed', evidence_json=?, completed_at=?, started_at=COALESCE(NULLIF(started_at,''), ?)
			WHERE step_id=? AND status!='completed'`,
			string(ev), now, now, stepID,
		)
		if err != nil {
			return err
		}
	}
	_, err := s.db.Exec(`UPDATE fleet_jobs SET status='running', updated_at=? WHERE job_id=?`, now, jobID)
	return err
}

// OnTransferAck completes receive step and may close the job. Returns user summary if completed.
func (s *JobStore) OnTransferAck(transferID, ackStatus string, evidence map[string]any) (completed *Job, summary string, err error) {
	var jobID, stepID string
	row := s.db.QueryRow(
		`SELECT job_id, step_id FROM fleet_job_transfers WHERE transfer_id=?`, transferID,
	)
	if err := row.Scan(&jobID, &stepID); err == sql.ErrNoRows {
		return nil, "", nil
	} else if err != nil {
		return nil, "", err
	}
	now := time.Now().UTC().Format(time.RFC3339)
	ev, _ := json.Marshal(evidence)
	stepStatus := "failed"
	if ackStatus == "ok" {
		stepStatus = "completed"
	}
	_, err = s.db.Exec(`
		UPDATE fleet_job_steps SET status=?, evidence_json=?, completed_at=?, started_at=COALESCE(NULLIF(started_at,''), ?)
		WHERE step_id=?`,
		stepStatus, string(ev), now, now, jobID+"-S4",
	)
	if err != nil {
		return nil, "", err
	}
	if stepStatus == "failed" {
		_, _ = s.db.Exec(`UPDATE fleet_jobs SET status='failed', updated_at=? WHERE job_id=?`, now, jobID)
		j, _ := s.GetJob(jobID)
		if j != nil {
			return j, fmt.Sprintf("%s 失败：接收未确认。", jobID), nil
		}
		return nil, "", nil
	}
	j, err := s.finalizeJobIfDone(jobID)
	if err != nil {
		return nil, "", err
	}
	if j == nil || j.Status != "completed" {
		return j, "", nil
	}
	summary = formatJobCompleteSummary(j)
	return j, summary, nil
}

func (s *JobStore) finalizeJobIfDone(jobID string) (*Job, error) {
	steps, err := s.listSteps(jobID)
	if err != nil {
		return nil, err
	}
	for _, st := range steps {
		if st.Mandatory && st.Status != "completed" {
			return s.GetJob(jobID)
		}
	}
	now := time.Now().UTC().Format(time.RFC3339)
	summary := ""
	j, _ := s.GetJob(jobID)
	if j != nil {
		summary = formatJobCompleteSummary(j)
	}
	_, err = s.db.Exec(`
		UPDATE fleet_jobs SET status='completed', summary=?, updated_at=?, closed_at=?
		WHERE job_id=?`, summary, now, now, jobID,
	)
	if err != nil {
		return nil, err
	}
	return s.GetJob(jobID)
}

func formatJobCompleteSummary(j *Job) string {
	if j == nil {
		return ""
	}
	sender, _ := j.Plan["sender_agent_id"].(string)
	receiver, _ := j.Plan["receiver_agent_id"].(string)
	hint, _ := j.Plan["file_hint"].(string)
	if hint == "" {
		hint = "文件"
	}
	senderLabel, _ := j.Plan["sender_display_name"].(string)
	receiverLabel, _ := j.Plan["receiver_display_name"].(string)
	if senderLabel == "" {
		senderLabel = sender
	}
	if receiverLabel == "" {
		receiverLabel = receiver
	}
	if sender == "" && receiver == "" {
		if j.Intent != "" {
			return fmt.Sprintf("%s 已完成。%s", j.JobID, j.Intent)
		}
		return fmt.Sprintf("%s 已完成。", j.JobID)
	}
	return fmt.Sprintf(
		"%s 已完成。%s → %s：%s 已保存至接收机 Incoming。",
		j.JobID, senderLabel, receiverLabel, hint,
	)
}

func (s *JobStore) ListJobs(userID string, limit int) ([]*Job, error) {
	if userID == "" {
		return nil, fmt.Errorf("user_id required")
	}
	if limit <= 0 || limit > 100 {
		limit = 30
	}
	rows, err := s.db.Query(`
		SELECT job_id FROM fleet_jobs WHERE user_id=?
		ORDER BY updated_at DESC LIMIT ?`, userID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	out := make([]*Job, 0, len(ids))
	for _, id := range ids {
		j, err := s.GetJob(id)
		if err != nil {
			return nil, err
		}
		out = append(out, j)
	}
	return out, nil
}

type ReportStepInput struct {
	Status   string
	Evidence map[string]any
	Error    string
}

func (s *JobStore) ReportStep(jobID, stepID string, in ReportStepInput) (*Job, error) {
	if jobID == "" || stepID == "" {
		return nil, fmt.Errorf("job_id and step_id required")
	}
	status := in.Status
	if status != "completed" && status != "failed" {
		return nil, fmt.Errorf("status must be completed or failed")
	}
	now := time.Now().UTC().Format(time.RFC3339)
	ev, _ := json.Marshal(in.Evidence)
	if ev == nil {
		ev = []byte("{}")
	}
	res, err := s.db.Exec(`
		UPDATE fleet_job_steps SET status=?, evidence_json=?, error_text=?,
			completed_at=?, started_at=COALESCE(NULLIF(started_at,''), ?)
		WHERE step_id=? AND job_id=?`,
		status, string(ev), in.Error, now, now, stepID, jobID,
	)
	if err != nil {
		return nil, err
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return nil, fmt.Errorf("step not found")
	}
	if status == "failed" {
		summary := fmt.Sprintf("%s 失败：%s", jobID, in.Error)
		if in.Error == "" {
			summary = fmt.Sprintf("%s 失败。", jobID)
		}
		_, err = s.db.Exec(`
			UPDATE fleet_jobs SET status='failed', summary=?, updated_at=?, closed_at=?
			WHERE job_id=?`, summary, now, now, jobID)
		if err != nil {
			return nil, err
		}
		return s.GetJob(jobID)
	}
	_, _ = s.db.Exec(`UPDATE fleet_jobs SET status='running', updated_at=? WHERE job_id=? AND status IN ('planned','created')`, now, jobID)
	return s.finalizeJobIfDone(jobID)
}

func (s *JobStore) DispatchStep(jobID, stepID, executorID string) (*Job, error) {
	if jobID == "" {
		return nil, fmt.Errorf("job_id required")
	}
	job, err := s.GetJob(jobID)
	if err != nil {
		return nil, err
	}
	if stepID == "" {
		for _, st := range job.Steps {
			if st.Status == "pending" {
				stepID = st.StepID
				if executorID == "" {
					executorID = st.ExecutorID
				}
				break
			}
		}
	}
	if stepID == "" {
		return nil, fmt.Errorf("no pending step")
	}
	if executorID == "" {
		executorID = "lingji-pc"
	}
	now := time.Now().UTC().Format(time.RFC3339)
	_, err = s.db.Exec(`
		UPDATE fleet_job_steps SET status='dispatched', executor_id=?,
			started_at=COALESCE(NULLIF(started_at,''), ?)
		WHERE step_id=? AND job_id=? AND status IN ('pending','dispatched')`,
		executorID, now, stepID, jobID,
	)
	if err != nil {
		return nil, err
	}
	_, err = s.db.Exec(`UPDATE fleet_jobs SET status='running', updated_at=? WHERE job_id=?`, now, jobID)
	if err != nil {
		return nil, err
	}
	return s.GetJob(jobID)
}

func (s *JobStore) FailStaleDispatched(timeout time.Duration) ([]*Job, error) {
	if timeout <= 0 {
		timeout = 30 * time.Minute
	}
	cutoff := time.Now().UTC().Add(-timeout).Format(time.RFC3339)
	rows, err := s.db.Query(`
		SELECT DISTINCT job_id FROM fleet_job_steps
		WHERE status='dispatched' AND started_at != '' AND started_at < ?`, cutoff)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	var out []*Job
	now := time.Now().UTC().Format(time.RFC3339)
	for _, id := range ids {
		_, _ = s.db.Exec(`
			UPDATE fleet_job_steps SET status='failed', error_text='dispatch timeout',
				completed_at=? WHERE job_id=? AND status='dispatched'`, now, id)
		_, _ = s.db.Exec(`
			UPDATE fleet_jobs SET status='failed', summary=?, updated_at=?, closed_at=?
			WHERE job_id=?`, id+" 失败：执行机无回执", now, now, id)
		j, err := s.GetJob(id)
		if err == nil {
			out = append(out, j)
		}
	}
	return out, nil
}
