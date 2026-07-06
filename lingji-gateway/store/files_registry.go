package store

import (
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"fmt"
	"strings"
	"time"
)

// LingjiFile is a user-visible file identity in the Fleet pipeline.
type LingjiFile struct {
	LingjiFileID   string `json:"lingji_file_id"`
	UserID         string `json:"user_id"`
	Name           string `json:"name"`
	SizeBytes      int64  `json:"size_bytes"`
	Mime           string `json:"mime"`
	HolderAgentID  string `json:"holder_agent_id"`
	LocalPath      string `json:"local_path,omitempty"`
	GatewayFileID  string `json:"gateway_file_id,omitempty"`
	SourceAgentID  string `json:"source_agent_id,omitempty"`
	CreatedAt      string `json:"created_at"`
	UpdatedAt      string `json:"updated_at"`
}

// FileRegistryStore persists LF-ID metadata (same SQLite file as inbox).
type FileRegistryStore struct {
	db *sql.DB
}

func OpenFileRegistry(path string) (*FileRegistryStore, error) {
	inbox, err := OpenInboxStore(path)
	if err != nil {
		return nil, err
	}
	return NewFileRegistryFromDB(inbox.DB())
}

// NewFileRegistryFromDB reuses an existing inbox database handle.
func NewFileRegistryFromDB(db *sql.DB) (*FileRegistryStore, error) {
	fr := &FileRegistryStore{db: db}
	if err := fr.migrate(); err != nil {
		return nil, err
	}
	return fr, nil
}

func (s *FileRegistryStore) migrate() error {
	_, err := s.db.Exec(`
		CREATE TABLE IF NOT EXISTS lingji_files (
			lingji_file_id TEXT PRIMARY KEY,
			user_id TEXT NOT NULL,
			name TEXT NOT NULL,
			size_bytes INTEGER NOT NULL DEFAULT 0,
			mime TEXT NOT NULL DEFAULT 'application/octet-stream',
			holder_agent_id TEXT NOT NULL DEFAULT '',
			local_path TEXT NOT NULL DEFAULT '',
			gateway_file_id TEXT NOT NULL DEFAULT '',
			source_agent_id TEXT NOT NULL DEFAULT '',
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		);
		CREATE INDEX IF NOT EXISTS idx_lingji_files_user
			ON lingji_files(user_id, updated_at DESC);
	`)
	return err
}

func MintLingjiFileID() (string, error) {
	b := make([]byte, 4)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return "LF-" + strings.ToUpper(hex.EncodeToString(b)), nil
}

func (s *FileRegistryStore) Register(f *LingjiFile) error {
	if f.LingjiFileID == "" {
		id, err := MintLingjiFileID()
		if err != nil {
			return err
		}
		f.LingjiFileID = id
	}
	now := time.Now().UTC().Format(time.RFC3339)
	if f.CreatedAt == "" {
		f.CreatedAt = now
	}
	f.UpdatedAt = now
	_, err := s.db.Exec(`
		INSERT INTO lingji_files (
			lingji_file_id, user_id, name, size_bytes, mime,
			holder_agent_id, local_path, gateway_file_id, source_agent_id,
			created_at, updated_at
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		ON CONFLICT(lingji_file_id) DO UPDATE SET
			name=excluded.name,
			size_bytes=excluded.size_bytes,
			mime=excluded.mime,
			holder_agent_id=excluded.holder_agent_id,
			local_path=excluded.local_path,
			gateway_file_id=excluded.gateway_file_id,
			source_agent_id=excluded.source_agent_id,
			updated_at=excluded.updated_at
	`, f.LingjiFileID, f.UserID, f.Name, f.SizeBytes, f.Mime,
		f.HolderAgentID, f.LocalPath, f.GatewayFileID, f.SourceAgentID,
		f.CreatedAt, f.UpdatedAt)
	return err
}

func (s *FileRegistryStore) UpdateHolder(lingjiFileID, holderAgentID, localPath string) error {
	now := time.Now().UTC().Format(time.RFC3339)
	res, err := s.db.Exec(`
		UPDATE lingji_files SET holder_agent_id=?, local_path=?, updated_at=?
		WHERE lingji_file_id=?
	`, holderAgentID, localPath, now, lingjiFileID)
	if err != nil {
		return err
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return fmt.Errorf("lingji_file_id not found: %s", lingjiFileID)
	}
	return nil
}

func (s *FileRegistryStore) Get(userID, lingjiFileID string) (*LingjiFile, error) {
	row := s.db.QueryRow(`
		SELECT lingji_file_id, user_id, name, size_bytes, mime,
			holder_agent_id, local_path, gateway_file_id, source_agent_id,
			created_at, updated_at
		FROM lingji_files WHERE lingji_file_id=? AND user_id=?
	`, lingjiFileID, userID)
	var f LingjiFile
	if err := row.Scan(
		&f.LingjiFileID, &f.UserID, &f.Name, &f.SizeBytes, &f.Mime,
		&f.HolderAgentID, &f.LocalPath, &f.GatewayFileID, &f.SourceAgentID,
		&f.CreatedAt, &f.UpdatedAt,
	); err != nil {
		return nil, err
	}
	return &f, nil
}
