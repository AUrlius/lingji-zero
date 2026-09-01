package store_test

import (
	"path/filepath"
	"testing"

	"github.com/AUrlius/lingji-gateway/store"
)

func TestHitlPendingUpsertListResolve(t *testing.T) {
	path := filepath.Join(t.TempDir(), "inbox.db")
	inbox, err := store.OpenInboxStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer inbox.Close()

	hitl, err := store.NewHitlPendingFromDB(inbox.DB())
	if err != nil {
		t.Fatal(err)
	}

	entry := &store.HitlPending{
		TaskID:      "task-1",
		UserID:      "user-abc",
		AgentID:     "lingji-laptop",
		ThreadID:    "user-abc:t1",
		Description: "deploy git pull",
		Tool:        "execute_command",
		RiskLevel:   "critical",
	}
	if err := hitl.UpsertPending(entry); err != nil {
		t.Fatal(err)
	}

	items, err := hitl.ListPending("user-abc")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 {
		t.Fatalf("pending len = %d, want 1", len(items))
	}
	if items[0].AgentID != "lingji-laptop" {
		t.Fatalf("agent_id = %q", items[0].AgentID)
	}

	entry.Description = "updated desc"
	if err := hitl.UpsertPending(entry); err != nil {
		t.Fatal(err)
	}
	items, err = hitl.ListPending("user-abc")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 1 {
		t.Fatalf("after upsert pending len = %d, want 1", len(items))
	}
	if items[0].Description != "updated desc" {
		t.Fatalf("description = %q", items[0].Description)
	}

	if err := hitl.Resolve("task-1", "resolved"); err != nil {
		t.Fatal(err)
	}
	items, err = hitl.ListPending("user-abc")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 0 {
		t.Fatalf("after resolve pending len = %d, want 0", len(items))
	}

	// Re-broadcast HITL_REQ must not resurrect a resolved approval.
	entry.Status = "pending"
	if err := hitl.UpsertPending(entry); err != nil {
		t.Fatal(err)
	}
	items, err = hitl.ListPending("user-abc")
	if err != nil {
		t.Fatal(err)
	}
	if len(items) != 0 {
		t.Fatalf("resolved HITL must not reopen on UpsertPending, pending len = %d", len(items))
	}
}

func TestHitlPendingSchedulerHiddenFromUserList(t *testing.T) {
	path := filepath.Join(t.TempDir(), "inbox.db")
	inbox, err := store.OpenInboxStore(path)
	if err != nil {
		t.Fatal(err)
	}
	defer inbox.Close()

	hitl, err := store.NewHitlPendingFromDB(inbox.DB())
	if err != nil {
		t.Fatal(err)
	}
	if err := hitl.UpsertPending(&store.HitlPending{
		TaskID:           "t-sched",
		UserID:           "user-abc",
		AgentID:          "lingji-pc",
		Escalation:       "scheduler",
		SchedulerAgentID: "lingji-laptop",
		JobID:            "LJ-1",
	}); err != nil {
		t.Fatal(err)
	}
	if err := hitl.UpsertPending(&store.HitlPending{
		TaskID:     "t-user",
		UserID:     "user-abc",
		AgentID:    "lingji-pc",
		Escalation: "user",
	}); err != nil {
		t.Fatal(err)
	}

	dock, err := hitl.ListPending("user-abc")
	if err != nil {
		t.Fatal(err)
	}
	if len(dock) != 1 || dock[0].TaskID != "t-user" {
		t.Fatalf("user dock = %+v", dock)
	}
	sched, err := hitl.ListPendingFiltered("user-abc", "scheduler")
	if err != nil {
		t.Fatal(err)
	}
	if len(sched) != 1 || sched[0].JobID != "LJ-1" {
		t.Fatalf("scheduler list = %+v", sched)
	}
}
