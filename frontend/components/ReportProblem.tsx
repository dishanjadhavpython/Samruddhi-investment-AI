import { Flag } from "lucide-react";
import { useState } from "react";
import { FEEDBACK_CATEGORIES, FeedbackCategory, FeedbackSurface } from "../lib/ai";
import { useApi } from "../lib/http";
import { showToast } from "./Toast";
import { Button, Field, Modal } from "./ui";

const SURFACE_NAMES: Record<FeedbackSurface, string> = {
  report: "the written report",
  retirement: "the retirement analysis",
  charts: "the charts",
  market_narrative: "today's market note",
  other: "an AI-written text",
};

const MAX_MESSAGE = 2000;

interface ReportProblemModalProps {
  open: boolean;
  onClose: () => void;
  surface: FeedbackSurface;
  jobId?: string;
}

/** Sends a problem with AI-written text to /api/ai-feedback for a person to review */
export function ReportProblemModal({ open, onClose, surface, jobId }: ReportProblemModalProps) {
  const api = useApi();
  const [category, setCategory] = useState<FeedbackCategory | null>(null);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    if (sending) return;
    setCategory(null);
    setMessage("");
    setError(null);
    onClose();
  };

  const send = async () => {
    if (!category) {
      setError("Choose what kind of problem it is.");
      return;
    }
    setSending(true);
    setError(null);
    try {
      await api("/api/ai-feedback", {
        method: "POST",
        body: JSON.stringify({ surface, category, message: message.trim() || null, job_id: jobId ?? null }),
      });
      showToast("success", "Report sent. Someone reviews every one.");
      setSending(false);
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't send the report. Try again.");
      setSending(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Report a problem"
      description={`Tell us what's wrong with ${SURFACE_NAMES[surface]}. A person reviews every report.`}
      footer={
        <>
          <Button variant="secondary" onClick={close} disabled={sending}>
            Cancel
          </Button>
          <Button onClick={send} loading={sending}>
            Send report
          </Button>
        </>
      }
    >
      <fieldset className="space-y-2">
        <legend className="mb-2 text-[13px] font-medium text-ink">What kind of problem?</legend>
        {FEEDBACK_CATEGORIES.map((c) => (
          <label
            key={c.value}
            className={`flex cursor-pointer items-start gap-3 rounded-[14px] border px-3.5 py-2.5 transition-colors ${
              category === c.value ? "border-accent bg-accent-soft" : "border-line hover:bg-sunken"
            }`}
          >
            <input
              type="radio"
              name="problem-category"
              value={c.value}
              checked={category === c.value}
              onChange={() => setCategory(c.value)}
              className="mt-1 accent-[var(--accent)]"
            />
            <span>
              <span className="block text-[13.5px] font-medium text-ink">{c.label}</span>
              <span className="block text-[12.5px] leading-5 text-muted">{c.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <div className="mt-4">
        <Field
          label="What did you notice? (optional)"
          htmlFor="problem-message"
          hint={`${message.length.toLocaleString("en-IN")} / ${MAX_MESSAGE.toLocaleString("en-IN")}. Don't include passwords or account numbers.`}
          error={error}
        >
          <textarea
            id="problem-message"
            rows={3}
            maxLength={MAX_MESSAGE}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            className="sm-field !h-auto py-2.5 leading-6"
            placeholder="For example: the second paragraph says the index is 12% below its high, but the Market page says 10%."
          />
        </Field>
      </div>
    </Modal>
  );
}

/** A small text button that opens ReportProblemModal */
export function ReportProblemButton({ surface, jobId, className = "" }: { surface: FeedbackSurface; jobId?: string; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={`sm-no-print inline-flex items-center gap-1.5 rounded-lg text-[12.5px] font-medium text-muted underline-offset-4 hover:text-ink hover:underline ${className}`}
      >
        <Flag className="h-3.5 w-3.5" strokeWidth={2} />
        Report a problem
      </button>
      <ReportProblemModal open={open} onClose={() => setOpen(false)} surface={surface} jobId={jobId} />
    </>
  );
}
