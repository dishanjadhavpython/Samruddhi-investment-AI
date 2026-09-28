import Link from "next/link";
import { SEBI_RISK_WARNING } from "./Disclosure";
import { Button, Modal } from "./ui";

interface AiDisclosureModalProps {
  open: boolean;
  accepting: boolean;
  onAccept: () => void;
  onCancel: () => void;
}

const POINTS: { title: string; body: string }[] = [
  {
    title: "What the AI reads",
    body: "The holdings, cash and targets you entered, today's index figures, and research notes from the last 14 days. Never your name or email.",
  },
  {
    title: "What it won't do",
    body: "Tell you to buy, sell or hold anything, name a price target, or say whether now is a good time to invest.",
  },
  {
    title: "How it's checked",
    body: "Every text passes content rules, a separate AI reviewer and a quality check before you see it. Failing text is withheld, and no person reads it first.",
  },
  {
    title: "What it can get wrong",
    body: "Analyses can be incomplete or wrong. Treat them as a description of your portfolio, not advice. Every run is logged so it can be checked later.",
  },
];

/** Shown once, before the first analysis; accepting is saved on the account */
export default function AiDisclosureModal({ open, accepting, onAccept, onCancel }: AiDisclosureModalProps) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      width="max-w-lg"
      title="Before your first analysis"
      description="Samruddhi AI's analyses are written by AI models (Amazon Nova Pro on AWS Bedrock). Samruddhi AI is not registered with SEBI as an Investment Adviser or Research Analyst."
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={accepting}>
            Not now
          </Button>
          <Button onClick={onAccept} loading={accepting} data-autofocus>
            I understand, run the analysis
          </Button>
        </>
      }
    >
      <dl className="space-y-3">
        {POINTS.map((p) => (
          <div key={p.title}>
            <dt className="text-[13.5px] font-semibold text-ink">{p.title}</dt>
            <dd className="mt-0.5 text-[13.5px] leading-6 text-ink-2">{p.body}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 text-[12.5px] leading-5 text-muted">
        {SEBI_RISK_WARNING}{" "}
        <Link href="/ai-use" className="font-medium text-ink underline underline-offset-2" onClick={onCancel}>
          How AI is used here
        </Link>
      </p>
    </Modal>
  );
}
