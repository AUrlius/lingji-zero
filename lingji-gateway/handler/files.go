package handler

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/AUrlius/lingji-gateway/config"
	"github.com/google/uuid"
)

const defaultMaxFileBytes = 50 * 1024 * 1024 // 50MB MVP

type storedFile struct {
	ID           string
	Name         string
	Mime         string
	SizeBytes    int64
	Path         string
	DownloadTok  string
	ExpiresAt    time.Time
	Downloads    int
	MaxDownloads int
}

// FileStore 临时文件存储（磁盘 + TTL 清理）
type FileStore struct {
	mu     sync.RWMutex
	files  map[string]*storedFile
	cfg    *config.Config
	stopCh chan struct{}
}

func NewFileStore(cfg *config.Config) *FileStore {
	dir := cfg.FileStoreDir
	if dir == "" {
		dir = filepath.Join(os.TempDir(), "lingji-files")
	}
	if err := os.MkdirAll(dir, 0o700); err != nil {
		log.Printf("[Files] 创建存储目录失败: %v", err)
	}

	s := &FileStore{
		files:  make(map[string]*storedFile),
		cfg:    cfg,
		stopCh: make(chan struct{}),
	}
	go s.cleanupLoop()
	return s
}

func (s *FileStore) Stop() {
	close(s.stopCh)
}

func (s *FileStore) cleanupLoop() {
	ticker := time.NewTicker(5 * time.Minute)
	defer ticker.Stop()
	for {
		select {
		case <-s.stopCh:
			return
		case <-ticker.C:
			s.purgeExpired()
		}
	}
}

func (s *FileStore) purgeExpired() {
	now := time.Now()
	s.mu.Lock()
	defer s.mu.Unlock()
	for id, f := range s.files {
		if now.After(f.ExpiresAt) {
			_ = os.Remove(f.Path)
			delete(s.files, id)
		}
	}
}

func randomToken(n int) (string, error) {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

type uploadResponse struct {
	FileID       string `json:"file_id"`
	Name         string `json:"name"`
	SizeBytes    int64  `json:"size_bytes"`
	Mime         string `json:"mime"`
	DownloadPath string `json:"download_path"`
}

// FilesHandler HTTP 临时文件上传/下载
type FilesHandler struct {
	store  *FileStore
	config *config.Config
}

func NewFilesHandler(cfg *config.Config) *FilesHandler {
	return &FilesHandler{
		store:  NewFileStore(cfg),
		config: cfg,
	}
}

func (h *FilesHandler) authOK(r *http.Request) bool {
	if h.config.AuthToken == "" {
		return true
	}
	if auth := r.Header.Get("Authorization"); auth == "Bearer "+h.config.AuthToken {
		return true
	}
	if r.URL.Query().Get("token") == h.config.AuthToken {
		return true
	}
	return false
}

func (h *FilesHandler) downloadAuthOK(r *http.Request, f *storedFile) bool {
	if tok := r.URL.Query().Get("token"); tok != "" {
		return tok == f.DownloadTok || (h.config.AuthToken != "" && tok == h.config.AuthToken)
	}
	return h.authOK(r)
}

func (h *FilesHandler) maxBytes() int64 {
	if h.config.FileMaxSizeBytes > 0 {
		return h.config.FileMaxSizeBytes
	}
	return defaultMaxFileBytes
}

func (h *FilesHandler) ttl() time.Duration {
	if h.config.FileTTL > 0 {
		return h.config.FileTTL
	}
	return time.Hour
}

func (h *FilesHandler) maxDownloads() int {
	if h.config.FileMaxDownloads > 0 {
		return h.config.FileMaxDownloads
	}
	return 10
}

func (h *FilesHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/files")
	path = strings.TrimPrefix(path, "/")
	if path == "" {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		h.handleUpload(w, r)
		return
	}
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	h.handleDownload(w, r, path)
}

func sanitizeUploadFilename(name string) string {
	name = filepath.Base(strings.TrimSpace(name))
	if name == "" || name == "." || name == ".." {
		return "upload"
	}
	return name
}

func (h *FilesHandler) handleUpload(w http.ResponseWriter, r *http.Request) {
	if !h.authOK(r) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	maxBytes := h.maxBytes()
	r.Body = http.MaxBytesReader(w, r.Body, maxBytes+1024)

	if err := r.ParseMultipartForm(maxBytes + 1024); err != nil {
		http.Error(w, "payload too large or invalid multipart", http.StatusRequestEntityTooLarge)
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		http.Error(w, "missing file field", http.StatusBadRequest)
		return
	}
	defer file.Close()

	name := sanitizeUploadFilename(header.Filename)
	if name == "upload" && header.Filename == "" {
		name = "download.bin"
	}
	if alt := r.FormValue("name"); alt != "" {
		name = sanitizeUploadFilename(alt)
	}

	id := uuid.New().String()
	dlTok, err := randomToken(16)
	if err != nil {
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}

	dir := h.store.cfg.FileStoreDir
	if dir == "" {
		dir = filepath.Join(os.TempDir(), "lingji-files")
	}
	_ = os.MkdirAll(dir, 0o700)
	destPath := filepath.Join(dir, id)

	dest, err := os.Create(destPath)
	if err != nil {
		http.Error(w, "storage error", http.StatusInternalServerError)
		return
	}
	written, err := io.Copy(dest, file)
	dest.Close()
	if err != nil {
		_ = os.Remove(destPath)
		http.Error(w, "upload failed", http.StatusInternalServerError)
		return
	}
	if written > maxBytes {
		_ = os.Remove(destPath)
		http.Error(w, fmt.Sprintf("file exceeds limit (%d bytes)", maxBytes), http.StatusRequestEntityTooLarge)
		return
	}

	mimeType := header.Header.Get("Content-Type")
	if mimeType == "" || mimeType == "application/octet-stream" {
		mimeType = mime.TypeByExtension(filepath.Ext(name))
	}
	if mimeType == "" {
		mimeType = "application/octet-stream"
	}

	entry := &storedFile{
		ID:           id,
		Name:         name,
		Mime:         mimeType,
		SizeBytes:    written,
		Path:         destPath,
		DownloadTok:  dlTok,
		ExpiresAt:    time.Now().Add(h.ttl()),
		MaxDownloads: h.maxDownloads(),
	}

	h.store.mu.Lock()
	h.store.files[id] = entry
	h.store.mu.Unlock()

	resp := uploadResponse{
		FileID:       id,
		Name:         name,
		SizeBytes:    written,
		Mime:         mimeType,
		DownloadPath: fmt.Sprintf("/files/%s?token=%s", id, dlTok),
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

func (h *FilesHandler) handleDownload(w http.ResponseWriter, r *http.Request, fileID string) {
	h.store.mu.RLock()
	f, ok := h.store.files[fileID]
	h.store.mu.RUnlock()
	if !ok || time.Now().After(f.ExpiresAt) {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	if !h.downloadAuthOK(r, f) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	h.store.mu.Lock()
	if f.Downloads >= f.MaxDownloads {
		h.store.mu.Unlock()
		http.Error(w, "download limit exceeded", http.StatusGone)
		return
	}
	f.Downloads++
	h.store.mu.Unlock()

	w.Header().Set("Content-Type", f.Mime)
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, f.Name))
	http.ServeFile(w, r, f.Path)
}
