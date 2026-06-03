package handler

import (
	"bytes"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/AUrlius/lingji-gateway/config"
)

func testFilesHandler(t *testing.T) *FilesHandler {
	t.Helper()
	dir, err := os.MkdirTemp("", "lingji-files-test-*")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })

	cfg := &config.Config{
		AuthToken:        "test-token",
		FileStoreDir:     dir,
		FileMaxSizeBytes: 1024 * 1024,
		FileTTL:          time.Hour,
		FileMaxDownloads: 3,
	}
	return NewFilesHandler(cfg)
}

func multipartUpload(t *testing.T, h *FilesHandler, name, content string) *httptest.ResponseRecorder {
	t.Helper()
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	part, err := writer.CreateFormFile("file", name)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.WriteString(part, content); err != nil {
		t.Fatal(err)
	}
	writer.Close()

	req := httptest.NewRequest(http.MethodPost, "/files", body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("Authorization", "Bearer test-token")
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)
	return rr
}

func TestFilesUploadAndDownload(t *testing.T) {
	h := testFilesHandler(t)
	up := multipartUpload(t, h, "hello.txt", "hello g6")
	if up.Code != http.StatusOK {
		t.Fatalf("upload status=%d body=%s", up.Code, up.Body.String())
	}
	body := up.Body.String()
	if !strings.Contains(body, "download_path") {
		t.Fatalf("missing download_path: %s", body)
	}
	pathStart := strings.Index(body, "/files/")
	if pathStart < 0 {
		t.Fatal("missing /files/ in response")
	}
	pathEnd := strings.Index(body[pathStart:], `"`)
	if pathEnd < 0 {
		t.Fatal("malformed download_path")
	}
	downloadPath := body[pathStart : pathStart+pathEnd]

	req := httptest.NewRequest(http.MethodGet, downloadPath, nil)
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)
	if rr.Code != http.StatusOK {
		t.Fatalf("download status=%d", rr.Code)
	}
	if rr.Body.String() != "hello g6" {
		t.Fatalf("content mismatch: %q", rr.Body.String())
	}
}

func TestFilesUploadUnauthorized(t *testing.T) {
	h := testFilesHandler(t)
	body := &bytes.Buffer{}
	writer := multipart.NewWriter(body)
	part, _ := writer.CreateFormFile("file", "x.txt")
	io.WriteString(part, "x")
	writer.Close()

	req := httptest.NewRequest(http.MethodPost, "/files", body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)
	if rr.Code != http.StatusUnauthorized {
		t.Fatalf("want 401 got %d", rr.Code)
	}
}

func TestFilesDownloadBadToken(t *testing.T) {
	h := testFilesHandler(t)
	up := multipartUpload(t, h, "a.txt", "data")
	if up.Code != http.StatusOK {
		t.Fatal(up.Body.String())
	}
	req := httptest.NewRequest(http.MethodGet, "/files/not-a-real-id?token=bad", nil)
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)
	if rr.Code != http.StatusNotFound && rr.Code != http.StatusUnauthorized {
		t.Fatalf("unexpected status %d", rr.Code)
	}
}
