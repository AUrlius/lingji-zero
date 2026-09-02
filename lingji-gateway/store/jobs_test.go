package store

import (
	"testing"
	"time"
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

func TestJobStoreCodingRunStepName(t *testing.T) {
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
		UserID:           "u",
		SchedulerAgentID: "lingji-laptop",
		Intent:           "hello",
		Playbook:         "coding.cursor",
		Plan:             map[string]any{"executor_id": "lingji-pc", "brief": "write hi"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(job.Steps) != 1 || job.Steps[0].Name != "coding_run" {
		t.Fatalf("steps=%+v", job.Steps)
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

func TestJobStoreReportProgressKeepsDispatched(t *testing.T) {
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
		UserID: "u", SchedulerAgentID: "lingji-laptop",
		Intent: "s", Playbook: "agent.status",
		Plan: map[string]any{"executor_id": "lingji-pc"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := js.DispatchStep(job.JobID, "", "lingji-pc"); err != nil {
		t.Fatal(err)
	}
	mid, err := js.ReportStep(job.JobID, job.JobID+"-S1", ReportStepInput{
		Status:   "progress",
		Evidence: map[string]any{"log_tail": "still"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if mid.Status == "completed" || mid.Status == "failed" {
		t.Fatalf("job closed early: %s", mid.Status)
	}
	if mid.Steps[0].Status != "dispatched" {
		t.Fatalf("step %s", mid.Steps[0].Status)
	}
	if mid.Steps[0].Evidence["log_tail"] != "still" {
		t.Fatalf("evidence %+v", mid.Steps[0].Evidence)
	}
	if _, err := js.ReportStep(job.JobID, job.JobID+"-S1", ReportStepInput{Status: "nope"}); err == nil {
		t.Fatal("want error for nope")
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

func TestFailStaleDispatchedRespectsPlanTimeout(t *testing.T) {
	inbox, err := OpenInboxStore(t.TempDir() + "/inbox.db")
	if err != nil {
		t.Fatal(err)
	}
	defer inbox.Close()
	js, err := NewJobStoreFromDB(inbox.DB())
	if err != nil {
		t.Fatal(err)
	}

	coding, err := js.CreateJob(CreateJobInput{
		UserID:           "u",
		SchedulerAgentID: "lingji-laptop",
		Intent:           "long coding",
		Playbook:         "coding.cursor",
		Plan: map[string]any{
			"executor_id": "lingji-pc",
			"timeout_sec": 3600,
			"brief":       "write hi",
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := js.DispatchStep(coding.JobID, "", "lingji-pc"); err != nil {
		t.Fatal(err)
	}

	ops, err := js.CreateJob(CreateJobInput{
		UserID:           "u",
		SchedulerAgentID: "lingji-laptop",
		Intent:           "status",
		Playbook:         "agent.status",
		Plan:             map[string]any{"executor_id": "lingji-pc"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := js.DispatchStep(ops.JobID, "", "lingji-pc"); err != nil {
		t.Fatal(err)
	}

	started := time.Now().UTC().Add(-35 * time.Minute).Format(time.RFC3339)
	if _, err := inbox.DB().Exec(
		`UPDATE fleet_job_steps SET started_at=? WHERE status='dispatched'`, started,
	); err != nil {
		t.Fatal(err)
	}

	failed, err := js.FailStaleDispatched(30 * time.Minute)
	if err != nil {
		t.Fatal(err)
	}

	codingAfter, err := js.GetJob(coding.JobID)
	if err != nil {
		t.Fatal(err)
	}
	if codingAfter.Status == "failed" {
		t.Fatalf("coding job with timeout_sec=3600 must not fail at 35m; status=%s", codingAfter.Status)
	}

	opsAfter, err := js.GetJob(ops.JobID)
	if err != nil {
		t.Fatal(err)
	}
	if opsAfter.Status != "failed" {
		t.Fatalf("agent.status job at 35m must fail; status=%s failed=%d", opsAfter.Status, len(failed))
	}
}
