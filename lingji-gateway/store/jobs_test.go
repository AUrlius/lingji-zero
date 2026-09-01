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

func TestJobStorePlaybookAndReport(t *testing.T) {
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
		UserID:           "user-desk",
		SchedulerAgentID: "lingji-laptop",
		Intent:           "检查上海 Agent 状态",
		Playbook:         "agent.status",
		Plan:             map[string]any{"executor_id": "lingji-pc"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(job.Steps) != 1 || job.Steps[0].Name != "run_playbook" {
		t.Fatalf("steps = %+v", job.Steps)
	}
	if job.ApprovalScope == nil || job.ApprovalScope["auto_approve_tier0"] != true {
		t.Fatalf("scope = %+v", job.ApprovalScope)
	}
	listed, err := js.ListJobs("user-desk", 10)
	if err != nil || len(listed) != 1 {
		t.Fatalf("list: %v %+v", err, listed)
	}
	dispatched, err := js.DispatchStep(job.JobID, "", "lingji-pc")
	if err != nil {
		t.Fatal(err)
	}
	if dispatched.Steps[0].Status != "dispatched" {
		t.Fatalf("dispatch status %s", dispatched.Steps[0].Status)
	}
	done, err := js.ReportStep(job.JobID, job.JobID+"-S1", ReportStepInput{
		Status:   "completed",
		Evidence: map[string]any{"stdout": "ok"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if done.Status != "completed" {
		t.Fatalf("want completed got %s", done.Status)
	}
}
