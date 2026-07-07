package store

import (
	"database/sql"
	"fmt"
	"time"
)

// HitlPending is a user-visible approval request mirrored at Gateway.
type HitlPending struct {
	TaskID      string `json:"task_id"`
	UserID      string `json:"user_id"`
	AgentID     string `json:"agent_id"`
	ThreadID    string `json:"thread_id"`
	Description string `json:"description"`
	Tool        string `json:"tool"`
	RiskLevel   string `json:"risk_level"`
	Status      string `json:"status"`
	CreatedAt   string `json:"created_at"`
	UpdatedAt   string `json:"updated_at"`
}

// HitlPendingStore persists cross-device HITL requests (same SQLite as inbox).
type HitlPendingStore struct {
	db *sql.DB
}

// NewHitlPendingFromDB reuses an existing inbox database handle.
func NewHitlPendingFromDB(db *sql.DB) (*HitlPendingStore, error) {
	s := &HitlPendingStore{db: db}
	if err := s.migrate(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *HitlPendingStore) migrate() error {
	_, err := s.db.Exec(`
		CREATE TABLE IF NOT EXISTS hitl_pending (
			task_id TEXT PRIMARY KEY,
			user_id TEXT NOT NULL,
			agent_id TEXT NOT NULL DEFAULT '',
			thread_id TEXT NOT NULL DEFAULT '',
			description TEXT NOT NULL DEFAULT '',
			tool TEXT NOT NULL DEFAULT '',
			risk_level TEXT NOT NULL DEFAULT 'critical',
			status TEXT NOT NULL DEFAULT 'pending',
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);
		CREATE INDEX IF NOT EXISTS idx_hitl_pending_user
			ON hitl_pending(user_id, status, updated_at DESC);
	`)
	return err
}

func (s *HitlPendingStore) UpsertPending(p *HitlPending) error {
	if p.TaskID == "" || p.UserID == "" {
		return fmt.Errorf("task_id and user_id required")
	}
	now := time.Now().UTC().Format(time.RFC3339)
	if p.CreatedAt == "" {
		p.CreatedAt = now
	}
	if p.Status == "" {
		p.Status = "pending"
	}
	p.UpdatedAt = now
	_, err := s.db.Exec(`
		INSERT INTO hitl_pending (
			task_id, user_id, agent_id, thread_id, description,
			tool, risk_level, status, created_at, updated_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(task_id) DO UPDATE SET
			user_id=excluded.user_id,
			agent_id=excluded.agent_id,
			thread_id=excluded.thread_id,
			description=excluded.description,
			tool=excluded.tool,
			risk_level=excluded.risk_level,
			status=excluded.status,
			updated_at=excluded.updated_at
	`, p.TaskID, p.UserID, p.AgentID, p.ThreadID, p.Description,
		p.Tool, p.RiskLevel, p.Status, p.CreatedAt, p.UpdatedAt)
	return err
}

func (s *HitlPendingStore) Resolve(taskID, status string) error {
	if taskID == "" {
		return fmt.Errorf("task_id required")
	}
	if status == "" {
		status = "resolved"
	}
	now := time.Now().UTC().Format(time.RFC3339)
	res, err := s.db.Exec(`
		UPDATE hitl_pending SET status=?, updated_at=? WHERE task_id=? AND status='pending'
	`, status, now, taskID)
	if err != nil {
		return err
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return fmt.Errorf("hitl task not found or already resolved: %s", taskID)
	}
	return nil
}

func (s *HitlPendingStore) ListPending(userID string) ([]HitlPending, error) {
	if userID == "" {
		return nil, fmt.Errorf("user_id required")
	}
	rows, err := s.db.Query(`
		SELECT task_id, user_id, agent_id, thread_id, description,
			tool, risk_level, status, created_at, updated_at
		FROM hitl_pending
		WHERE user_id=? AND status='pending'
		ORDER BY updated_at DESC
	`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []HitlPending
	for rows.Next() {
		var p HitlPending
		if err := rows.Scan(
			&p.TaskID, &p.UserID, &p.AgentID, &p.ThreadID, &p.Description,
			&p.Tool, &p.RiskLevel, &p.Status, &p.CreatedAt, &p.UpdatedAt,
		); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}
