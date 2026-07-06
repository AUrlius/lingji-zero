package store_test

import (
	"path/filepath"
	"testing"

	"github.com/AUrlius/lingji-gateway/store"
)

func TestInboxStoreThreadsAndMessages(t *testing.T) {
	path := filepath.Join(t.TempDir(), "inbox.db")
	s, err := store.OpenInboxStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()

	if err := s.UpsertThread("user-abc:t1", "user-abc", "lingji-pc", "Hello"); err != nil {
		t.Fatal(err)
	}
	if err := s.UpsertThread("user-abc:t2", "user-abc", "lingji-laptop", "Laptop chat"); err != nil {
		t.Fatal(err)
	}
	if err := s.AppendMessage("user-abc:t1", "user-abc", "lingji-pc", "user", "hi", "web"); err != nil {
		t.Fatal(err)
	}
	if err := s.AppendMessage("user-abc:t1", "user-abc", "lingji-pc", "agent", "hello", "agent"); err != nil {
		t.Fatal(err)
	}

	threads, err := s.ListThreads("user-abc")
	if err != nil {
		t.Fatal(err)
	}
	if len(threads) != 2 {
		t.Fatalf("threads len = %d, want 2", len(threads))
	}

	msgs, err := s.ListMessages("user-abc:t1", "lingji-pc", 50)
	if err != nil {
		t.Fatal(err)
	}
	if len(msgs) != 2 {
		t.Fatalf("messages len = %d, want 2", len(msgs))
	}
	if msgs[0].Role != "user" || msgs[1].Role != "agent" {
		t.Fatalf("unexpected roles: %+v", msgs)
	}
}
