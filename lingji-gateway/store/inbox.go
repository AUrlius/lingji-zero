package store

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"time"

	_ "modernc.org/sqlite"
)

// Thread is a cross-agent conversation index row.
type Thread struct {
	ThreadID  string `json:"thread_id"`
	UserID    string `json:"user_id"`
	AgentID   string `json:"agent_id"`
	Title     string `json:"title"`
	UpdatedAt string `json:"updated_at"`
	Active    bool   `json:"active,omitempty"`
}

// Message is a single inbox transcript line.
type Message struct {
	ID        int64  `json:"id"`
	ThreadID  string `json:"thread_id"`
	AgentID   string `json:"agent_id"`
	UserID    string `json:"user_id"`
	Role      string `json:"role"`
	Text      string `json:"text"`
	Source    string `json:"source"`
	CreatedAt string `json:"created_at"`
}

// InboxStore persists Fleet Phase 2 inbox data in SQLite.
type InboxStore struct {
	db *sql.DB
}

// OpenInboxStore opens (or creates) the inbox database.
func OpenInboxStore(path string) (*InboxStore, error) {
	if path == "" {
		path = "inbox.db"
	}
	if dir := filepath.Dir(path); dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return nil, fmt.Errorf("inbox mkdir: %w", err)
		}
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	s := &InboxStore{db: db}
	if err := s.migrate(); err != nil {
		_ = db.Close()
		return nil, err
	}
	return s, nil
}

func (s *InboxStore) migrate() error {
	_, err := s.db.Exec(`
		CREATE TABLE IF NOT EXISTS inbox_threads (
			thread_id TEXT NOT NULL,
			user_id TEXT NOT NULL,
			agent_id TEXT NOT NULL,
			title TEXT NOT NULL DEFAULT '',
			updated_at TEXT NOT NULL,
			PRIMARY KEY (thread_id, agent_id)
		);
		CREATE INDEX IF NOT EXISTS idx_inbox_threads_user
			ON inbox_threads(user_id, updated_at DESC);

		CREATE TABLE IF NOT EXISTS inbox_messages (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			thread_id TEXT NOT NULL,
			agent_id TEXT NOT NULL,
			user_id TEXT NOT NULL,
			role TEXT NOT NULL,
			text TEXT NOT NULL,
			source TEXT NOT NULL DEFAULT 'web',
			created_at TEXT NOT NULL
		);
		CREATE INDEX IF NOT EXISTS idx_inbox_messages_thread
			ON inbox_messages(thread_id, agent_id, created_at);
	`)
	return err
}

// Close closes the database.
func (s *InboxStore) Close() error {
	if s == nil || s.db == nil {
		return nil
	}
	return s.db.Close()
}

// DB exposes the underlying SQLite handle (shared with file registry).
func (s *InboxStore) DB() *sql.DB {
	if s == nil {
		return nil
	}
	return s.db
}

func nowRFC3339() string {
	return time.Now().UTC().Format(time.RFC3339Nano)
}

// UpsertThread inserts or updates a thread row.
func (s *InboxStore) UpsertThread(threadID, userID, agentID, title string) error {
	if threadID == "" || userID == "" || agentID == "" {
		return nil
	}
	if title == "" {
		title = "新对话"
	}
	_, err := s.db.Exec(`
		INSERT INTO inbox_threads (thread_id, user_id, agent_id, title, updated_at)
		VALUES (?, ?, ?, ?, ?)
		ON CONFLICT(thread_id, agent_id) DO UPDATE SET
			user_id = excluded.user_id,
			title = CASE WHEN excluded.title != '' THEN excluded.title ELSE inbox_threads.title END,
			updated_at = excluded.updated_at
	`, threadID, userID, agentID, title, nowRFC3339())
	return err
}

// AppendMessage stores one transcript line (skips empty text).
func (s *InboxStore) AppendMessage(threadID, userID, agentID, role, text, source string) error {
	if threadID == "" || userID == "" || agentID == "" || text == "" {
		return nil
	}
	if role == "" {
		role = "user"
	}
	if source == "" {
		source = "web"
	}
	ts := nowRFC3339()
	_, err := s.db.Exec(`
		INSERT INTO inbox_messages (thread_id, agent_id, user_id, role, text, source, created_at)
		VALUES (?, ?, ?, ?, ?, ?, ?)
	`, threadID, agentID, userID, role, text, source, ts)
	if err != nil {
		return err
	}
	title := text
	if len([]rune(title)) > 40 {
		title = string([]rune(title)[:40]) + "…"
	}
	return s.UpsertThread(threadID, userID, agentID, title)
}

// ListThreads returns all threads for a user, newest first.
func (s *InboxStore) ListThreads(userID string) ([]Thread, error) {
	rows, err := s.db.Query(`
		SELECT thread_id, user_id, agent_id, title, updated_at
		FROM inbox_threads
		WHERE user_id = ?
		ORDER BY updated_at DESC
	`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]Thread, 0)
	for rows.Next() {
		var t Thread
		if err := rows.Scan(&t.ThreadID, &t.UserID, &t.AgentID, &t.Title, &t.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

// ListMessages returns messages for a thread on a specific agent.
func (s *InboxStore) ListMessages(threadID, agentID string, limit int) ([]Message, error) {
	if limit <= 0 {
		limit = 200
	}
	rows, err := s.db.Query(`
		SELECT id, thread_id, agent_id, user_id, role, text, source, created_at
		FROM inbox_messages
		WHERE thread_id = ? AND agent_id = ?
		ORDER BY id ASC
		LIMIT ?
	`, threadID, agentID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := make([]Message, 0)
	for rows.Next() {
		var m Message
		if err := rows.Scan(&m.ID, &m.ThreadID, &m.AgentID, &m.UserID, &m.Role, &m.Text, &m.Source, &m.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}
