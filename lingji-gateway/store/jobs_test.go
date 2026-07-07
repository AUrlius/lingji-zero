package store

import (
	"testing"
)

func TestJobStoreCreateAndComplete(t *testing.T) {
	inbox, err := OpenInboxStore(t.TempDir() + "/inbox.db")
	if err != nil {
		t.Fatal(err)
	}
	defer inbox.Close()

	js, err := NewJobStoreFromDB(inbox.DB())
	if err != nil {
		t.Fatal(err)
	}

	job, err := js.CreateJob(CreateJobInput{
		UserID:           "user-abc",
		SchedulerAgentID: "lingji-pc",
		Intent:           "空城记发 report 到青铜剑",
		Playbook:         "fleet.file_transfer",
		Plan: map[string]any{
			"sender_agent_id":       "lingji-laptop",
			"receiver_agent_id":     "lingji-pc",
			"sender_display_name":   "空城记",
			"receiver_display_name": "青铜剑",
			"file_hint":             "report.pdf",
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if job.JobID == "" || len(job.Steps) != 4 {
		t.Fatalf("unexpected job: %+v", job)
	}
	if job.Steps[0].Status != "completed" {
		t.Fatalf("S1 should be completed, got %s", job.Steps[0].Status)
	}

	tid := "transfer-uuid-1"
	if err := js.LinkTransfer(tid, job.JobID, job.JobID+"-S3"); err != nil {
		t.Fatal(err)
	}
	if err := js.OnTransferStarted(job.JobID, tid); err != nil {
		t.Fatal(err)
	}
	completed, summary, err := js.OnTransferAck(tid, "ok", map[string]any{"saved": []any{map[string]any{"name": "report.pdf"}}})
	if err != nil {
		t.Fatal(err)
	}
	if completed == nil || completed.Status != "completed" {
		t.Fatalf("expected completed job, got %+v", completed)
	}
	if summary == "" || completed.JobID != job.JobID {
		t.Fatalf("bad summary: %q job=%+v", summary, completed)
	}
}
