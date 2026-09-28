import { Download, FileUp, Pencil, Plus, Trash2 } from "lucide-react";
import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";
import { formatINR, formatNumberIN } from "../lib/currency";
import { useApi } from "../lib/http";
import ConfirmModal from "./ConfirmModal";
import { showToast } from "./Toast";
import { Badge, Button, Card, EmptyState, Field, Modal, Money, Skeleton } from "./ui";

export type TxnType =
  | "buy"
  | "sell"
  | "dividend"
  | "split"
  | "bonus"
  | "deposit"
  | "withdrawal"
  | "fee"
  | "interest"
  | "opening_balance";

export interface TxnRow {
  id: string;
  account_id: string;
  txn_type: TxnType;
  trade_date: string;
  symbol: string | null;
  quantity: number | null;
  price: number | null;
  amount: number | null;
  fees: number;
  cash_effect: number;
  source: "manual" | "csv" | "system";
  external_ref: string | null;
  note: string | null;
  account_name?: string;
}

export const TXN_LABELS: Record<TxnType, string> = {
  buy: "Buy",
  sell: "Sale",
  dividend: "Dividend",
  split: "Split",
  bonus: "Bonus",
  deposit: "Deposit",
  withdrawal: "Withdrawal",
  fee: "Fee",
  interest: "Interest",
  opening_balance: "Opening balance",
};

// What each type needs, mirroring backend/database/src/returns.py validate()
const NEEDS_SYMBOL = new Set<TxnType>(["buy", "sell", "dividend", "split", "bonus", "opening_balance"]);
const NEEDS_UNITS = new Set<TxnType>(["buy", "sell", "split", "bonus", "opening_balance"]);
const NEEDS_PRICE = new Set<TxnType>(["buy", "sell", "opening_balance"]);
const NEEDS_AMOUNT = new Set<TxnType>(["dividend", "deposit", "withdrawal", "fee", "interest"]);
const MOVES_CASH = new Set<TxnType>(["buy", "sell", "dividend", "deposit", "withdrawal", "fee", "interest"]);

const TYPE_ORDER: TxnType[] = ["buy", "sell", "dividend", "opening_balance", "bonus", "split", "deposit", "withdrawal", "interest", "fee"];

const today = () => {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
};

const formatDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

function cashEffect(type: TxnType, units: number, price: number, amount: number, fees: number): number {
  if (type === "buy") return -(units * price + fees);
  if (type === "sell") return units * price - fees;
  if (type === "dividend" || type === "interest" || type === "deposit") return amount;
  if (type === "withdrawal" || type === "fee") return -amount;
  return 0;
}

// ---------------------------------------------------------------------------
// Record / edit
// ---------------------------------------------------------------------------

interface FormState {
  type: TxnType;
  date: string;
  symbol: string;
  units: string;
  price: string;
  amount: string;
  fees: string;
  note: string;
  updateCash: boolean;
}

const blank = (): FormState => ({ type: "buy", date: today(), symbol: "", units: "", price: "", amount: "", fees: "", note: "", updateCash: false });

function fromRow(row: TxnRow): FormState {
  const s = (v: number | null) => (v == null ? "" : String(v));
  return {
    type: row.txn_type,
    date: row.trade_date.slice(0, 10),
    symbol: row.symbol ?? "",
    units: s(row.quantity),
    price: s(row.price),
    amount: NEEDS_AMOUNT.has(row.txn_type) ? s(row.amount) : "",
    fees: row.fees ? String(row.fees) : "",
    note: row.note ?? "",
    updateCash: Math.abs(row.cash_effect) > 0.004,
  };
}

export function TransactionModal({
  open,
  onClose,
  accountId,
  existing,
  symbols,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  accountId: string;
  existing: TxnRow | null;
  symbols: string[];
  onSaved: () => Promise<void>;
}) {
  const api = useApi();
  const [form, setForm] = useState<FormState>(blank);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(existing ? fromRow(existing) : blank());
      setError(null);
    }
  }, [open, existing]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const num = (text: string) => parseFloat(text.replace(/,/g, "")) || 0;
  const t = form.type;
  const effect = cashEffect(t, num(form.units), num(form.price), num(form.amount), num(form.fees));
  const editing = existing !== null;
  const estimated = existing?.source === "system";

  const submit = async () => {
    if (NEEDS_SYMBOL.has(t) && !form.symbol.trim()) return setError("Enter the symbol, for example NIFTYBEES.");
    if (NEEDS_UNITS.has(t) && !num(form.units)) return setError("Enter the number of units.");
    if ((t === "buy" || t === "sell") && !num(form.price)) return setError("Enter the price per unit.");
    if (NEEDS_AMOUNT.has(t) && !(num(form.amount) > 0)) return setError("Enter the amount.");
    if (form.date > today()) return setError("The date can't be in the future.");

    const values = {
      trade_date: form.date,
      quantity: NEEDS_UNITS.has(t) ? num(form.units) : null,
      price: NEEDS_PRICE.has(t) && form.price.trim() ? num(form.price) : null,
      amount: NEEDS_AMOUNT.has(t) ? num(form.amount) : null,
      fees: t === "buy" || t === "sell" ? num(form.fees) : 0,
      note: form.note.trim() || null,
    };
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await api(`/api/transactions/${existing.id}`, { method: "PUT", body: JSON.stringify(values) });
      } else {
        await api("/api/transactions", {
          method: "POST",
          body: JSON.stringify({
            ...values,
            account_id: accountId,
            txn_type: t,
            symbol: NEEDS_SYMBOL.has(t) || t === "fee" ? form.symbol.trim().toUpperCase() || null : null,
            update_cash: MOVES_CASH.has(t) && form.updateCash,
          }),
        });
      }
      await onSaved();
      showToast("success", editing ? "Transaction updated." : `${TXN_LABELS[t]} recorded.`);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save the transaction.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={editing ? `Edit ${TXN_LABELS[t].toLowerCase()}` : "Record a transaction"}
      description={
        estimated
          ? "The app created this opening balance from the quantity you entered and valued it at that day's close. Enter when you bought and at what price, and your returns are measured from then."
          : editing
            ? "The type, holding and account stay as they are. To change those, delete this row and record a new one."
            : "Holdings in this account are worked out from these rows."
      }
      width="max-w-lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving}>
            {editing ? "Save changes" : `Record ${TXN_LABELS[t].toLowerCase()}`}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Type" htmlFor="t-type">
          <select id="t-type" className="sm-field" value={t} disabled={editing} onChange={(e) => set("type", e.target.value as TxnType)}>
            {TYPE_ORDER.map((type) => (
              <option key={type} value={type}>
                {TXN_LABELS[type]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Date" htmlFor="t-date">
          <input id="t-date" type="date" className="sm-field" max={today()} value={form.date} onChange={(e) => set("date", e.target.value)} />
        </Field>

        {(NEEDS_SYMBOL.has(t) || t === "fee") && (
          <div className="sm:col-span-2">
            <Field label={t === "fee" ? "Holding (optional)" : "Holding"} htmlFor="t-symbol">
              <input
                id="t-symbol"
                className="sm-field uppercase placeholder:normal-case"
                list="t-symbols"
                disabled={editing}
                placeholder="NIFTYBEES"
                value={form.symbol}
                onChange={(e) => set("symbol", e.target.value)}
                autoComplete="off"
              />
              <datalist id="t-symbols">
                {symbols.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </Field>
          </div>
        )}

        {NEEDS_UNITS.has(t) && (
          <Field label={t === "split" || t === "bonus" ? "Units added" : "Units"} htmlFor="t-units" hint={t === "split" ? "Negative for a consolidation." : undefined}>
            <input id="t-units" className="sm-field" inputMode="decimal" type="number" step="any" value={form.units} onChange={(e) => set("units", e.target.value)} />
          </Field>
        )}
        {NEEDS_PRICE.has(t) && (
          <Field label={t === "opening_balance" ? "Average price paid" : "Price per unit"} htmlFor="t-price" hint={t === "opening_balance" ? "Leave empty if you don't know it." : undefined}>
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">₹</span>
              <input id="t-price" className="sm-field pl-7" inputMode="decimal" type="number" step="any" min="0" value={form.price} onChange={(e) => set("price", e.target.value)} />
            </div>
          </Field>
        )}
        {NEEDS_AMOUNT.has(t) && (
          <Field label="Amount" htmlFor="t-amount">
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">₹</span>
              <input id="t-amount" className="sm-field pl-7" inputMode="decimal" type="number" step="any" min="0" value={form.amount} onChange={(e) => set("amount", e.target.value)} />
            </div>
          </Field>
        )}
        {(t === "buy" || t === "sell") && (
          <Field label="Charges" htmlFor="t-fees" hint="Brokerage, STT, stamp duty and other charges.">
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">₹</span>
              <input id="t-fees" className="sm-field pl-7" inputMode="decimal" type="number" step="any" min="0" value={form.fees} onChange={(e) => set("fees", e.target.value)} />
            </div>
          </Field>
        )}

        <div className="sm:col-span-2">
          <Field label="Note (optional)" htmlFor="t-note">
            <input id="t-note" className="sm-field" maxLength={500} value={form.note} onChange={(e) => set("note", e.target.value)} />
          </Field>
        </div>

        {MOVES_CASH.has(t) && !editing && (
          <label className="flex items-start gap-2.5 rounded-xl bg-sunken px-3.5 py-3 text-[13px] text-ink-2 sm:col-span-2">
            <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={form.updateCash} onChange={(e) => set("updateCash", e.target.checked)} />
            <span>
              Also change this account&apos;s cash balance
              {effect !== 0 && (
                <span className="font-semibold text-ink">
                  {" "}
                  by {effect > 0 ? "+" : "−"}
                  {formatINR(Math.abs(effect))}
                </span>
              )}
              <span className="mt-0.5 block text-[12px] text-muted">Leave it off for older transactions that today&apos;s balance already reflects.</span>
            </span>
          </label>
        )}
        {editing && Math.abs(existing.cash_effect) > 0.004 && (
          <p className="text-[12.5px] text-muted sm:col-span-2">This row moved the account&apos;s cash; saving moves it again by any difference.</p>
        )}

        {error && <p className="text-[13px] text-bad sm:col-span-2">{error}</p>}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// CSV import
// ---------------------------------------------------------------------------

interface PreviewRow {
  line: number;
  txn_type: TxnType;
  trade_date: string;
  symbol: string | null;
  quantity: number | null;
  price: number | null;
  amount: number | null;
  fees: number;
}

interface Preview {
  rows: PreviewRow[];
  errors: { line: number; message: string }[];
  new_symbols: string[];
  columns: Record<string, string>;
}

export function ImportModal({ open, onClose, accountId, onImported }: { open: boolean; onClose: () => void; accountId: string; onImported: () => Promise<void> }) {
  const api = useApi();
  const [csv, setCsv] = useState("");
  const [fileName, setFileName] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [updateCash, setUpdateCash] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setCsv("");
      setFileName("");
      setPreview(null);
      setUpdateCash(false);
      setError(null);
    }
  }, [open]);

  const downloadTemplate = async () => {
    try {
      const { csv: text, filename } = await api<{ csv: string; filename: string }>("/api/transactions/template");
      const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Couldn't download the template.");
    }
  };

  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 2_000_000) return setError("That file is over 2 MB. Split it and import the parts.");
    const text = await file.text();
    setFileName(file.name);
    setCsv(text);
    setBusy(true);
    setError(null);
    try {
      setPreview(await api<Preview>("/api/transactions/import", { method: "POST", body: JSON.stringify({ account_id: accountId, csv: text, dry_run: true }) }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't read the file.");
    } finally {
      setBusy(false);
    }
  };

  const record = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ imported: number; duplicates: number; errors: { line: number; message: string }[] }>("/api/transactions/import", {
        method: "POST",
        body: JSON.stringify({ account_id: accountId, csv, dry_run: false, update_cash: updateCash }),
      });
      await onImported();
      const parts = [`${result.imported} recorded`];
      if (result.duplicates) parts.push(`${result.duplicates} already imported`);
      if (result.errors.length) parts.push(`${result.errors.length} skipped`);
      showToast(result.errors.length ? "error" : "success", `Import finished: ${parts.join(", ")}.`);
      if (result.errors.length) {
        setPreview((p) => (p ? { ...p, rows: [], errors: result.errors } : p));
      } else {
        onClose();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't import the file.");
    } finally {
      setBusy(false);
    }
  };

  const shown = preview?.rows.slice(0, 40) ?? [];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import transactions"
      description="A CSV with one transaction per line. The app's template works, and so does a broker tradebook with date, type, symbol, quantity and price columns."
      width="max-w-2xl"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {preview && !preview.rows.length ? "Close" : "Cancel"}
          </Button>
          {preview && preview.rows.length > 0 && (
            <Button onClick={record} loading={busy}>
              Record {preview.rows.length} transaction{preview.rows.length === 1 ? "" : "s"}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <label className="sm-btn sm-btn-secondary cursor-pointer">
            <FileUp className="h-4 w-4" strokeWidth={2} />
            {fileName ? "Choose another file" : "Choose a CSV file"}
            <input type="file" accept=".csv,text/csv" className="sr-only" onChange={onFile} />
          </label>
          <Button variant="ghost" onClick={downloadTemplate} icon={<Download className="h-4 w-4" strokeWidth={2} />}>
            Download the template
          </Button>
        </div>
        {fileName && <p className="text-[12.5px] text-muted">{fileName}</p>}
        {busy && !preview && <Skeleton className="h-32" />}

        {preview && (
          <>
            {preview.rows.length > 0 && (
              <div className="max-h-[300px] overflow-auto rounded-xl border border-line">
                <table className="w-full min-w-[520px] text-[12.5px]">
                  <thead className="sticky top-0 bg-sunken text-muted">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">Line</th>
                      <th className="px-3 py-2 text-left font-medium">Date</th>
                      <th className="px-3 py-2 text-left font-medium">Type</th>
                      <th className="px-3 py-2 text-left font-medium">Holding</th>
                      <th className="px-3 py-2 text-right font-medium">Units</th>
                      <th className="px-3 py-2 text-right font-medium">Price or amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((r) => (
                      <tr key={r.line} className="border-t border-line">
                        <td className="tabular px-3 py-1.5 text-muted">{r.line}</td>
                        <td className="tabular px-3 py-1.5 text-ink-2">{formatDate(r.trade_date)}</td>
                        <td className="px-3 py-1.5 text-ink">{TXN_LABELS[r.txn_type]}</td>
                        <td className="px-3 py-1.5 font-medium text-ink">{r.symbol ?? "—"}</td>
                        <td className="tabular px-3 py-1.5 text-right text-ink-2">{r.quantity != null ? formatNumberIN(r.quantity, r.quantity % 1 ? 2 : 0) : "—"}</td>
                        <td className="tabular px-3 py-1.5 text-right text-ink-2">
                          {r.price != null ? formatINR(r.price) : r.amount != null ? formatINR(r.amount) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {preview.rows.length > shown.length && <p className="text-[12.5px] text-muted">And {preview.rows.length - shown.length} more.</p>}
            {preview.new_symbols?.length > 0 && (
              <p className="text-[12.5px] text-muted">
                New to the app: {preview.new_symbols.join(", ")}. They&apos;re added to the catalogue, priced on the next run where a price is available, and
                classified on your next analysis.
              </p>
            )}
            {preview.errors.length > 0 && (
              <div className="rounded-xl bg-bad-soft px-3.5 py-3 text-[12.5px] text-bad">
                <p className="font-semibold">
                  {preview.errors.length} line{preview.errors.length === 1 ? "" : "s"} can&apos;t be recorded:
                </p>
                <ul className="mt-1.5 max-h-[140px] space-y-0.5 overflow-auto">
                  {preview.errors.map((e) => (
                    <li key={`${e.line}-${e.message}`}>
                      Line {e.line}: {e.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {preview.rows.length > 0 && (
              <label className="flex items-start gap-2.5 rounded-xl bg-sunken px-3.5 py-3 text-[13px] text-ink-2">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--accent)]" checked={updateCash} onChange={(e) => setUpdateCash(e.target.checked)} />
                <span>
                  Also change this account&apos;s cash balance by what these transactions paid and received
                  <span className="mt-0.5 block text-[12px] text-muted">Leave it off for history that today&apos;s balance already reflects.</span>
                </span>
              </label>
            )}
            <p className="text-[12px] text-muted">Importing the same file again skips rows already recorded.</p>
          </>
        )}
        {error && <p className="text-[13px] text-bad">{error}</p>}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// The account page's ledger card
// ---------------------------------------------------------------------------

export function useTransactions(accountId: string) {
  const api = useApi();
  const [rows, setRows] = useState<TxnRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!accountId) return;
    try {
      const data = await api<{ transactions: TxnRow[] }>(`/api/transactions?account_id=${encodeURIComponent(accountId)}`);
      setRows(data.transactions);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load transactions.");
    }
  }, [api, accountId]);

  useEffect(() => {
    load();
  }, [load]);

  return { rows, error, reload: load };
}

export function TransactionsCard({ accountId, symbols, onChanged }: { accountId: string; symbols: string[]; onChanged: () => Promise<void> }) {
  const api = useApi();
  const { rows, error, reload } = useTransactions(accountId);
  const [editing, setEditing] = useState<TxnRow | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [deleting, setDeleting] = useState<TxnRow | null>(null);
  const [working, setWorking] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [catalogue, setCatalogue] = useState<string[]>([]);

  // Symbol suggestions: this account's holdings first, then the catalogue (loaded when the form first opens)
  useEffect(() => {
    if (!formOpen || catalogue.length) return;
    api<{ symbol: string }[]>("/api/instruments")
      .then((items) => setCatalogue(Array.isArray(items) ? items.map((i) => i.symbol) : []))
      .catch(() => undefined);
  }, [formOpen, catalogue.length, api]);
  const suggestions = useMemo(() => Array.from(new Set([...symbols, ...catalogue])), [symbols, catalogue]);

  const changed = async () => {
    await Promise.all([reload(), onChanged()]);
  };

  const remove = async () => {
    if (!deleting) return;
    setWorking(true);
    try {
      await api(`/api/transactions/${deleting.id}`, { method: "DELETE" });
      await changed();
      showToast("success", `${TXN_LABELS[deleting.txn_type]} deleted.`);
      setDeleting(null);
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Couldn't delete it.");
    } finally {
      setWorking(false);
    }
  };

  const estimates = useMemo(() => (rows ?? []).filter((r) => r.source === "system").length, [rows]);
  const visible = showAll ? rows ?? [] : (rows ?? []).slice(0, 12);

  return (
    <Card
      title="Transactions"
      subtitle="The holdings above are worked out from these rows"
      action={
        <>
          <Button variant="ghost" size="sm" onClick={() => setImportOpen(true)} icon={<FileUp className="h-3.5 w-3.5" strokeWidth={2} />}>
            Import
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
            icon={<Plus className="h-3.5 w-3.5" strokeWidth={2.4} />}
          >
            Record
          </Button>
        </>
      }
      bodyClassName="!px-0 !pb-0"
    >
      {estimates > 0 && (
        <p className="mx-5 mb-3 rounded-xl bg-accent-soft px-3.5 py-2.5 text-[12.5px] leading-5 text-ink">
          {estimates === 1 ? "One opening balance is" : `${estimates} opening balances are`} valued at the close on the day you entered the holding. Edit{" "}
          {estimates === 1 ? "it" : "them"} with when you bought and at what price, and your returns are measured from then.
        </p>
      )}
      {error ? (
        <p className="px-5 pb-5 text-[13px] text-bad">{error}</p>
      ) : rows === null ? (
        <div className="px-5 pb-5">
          <Skeleton className="h-24" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState className="!py-8" title="No transactions yet" body="Record buys, sales and dividends, or import a CSV from your broker." />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-[13px]">
              <thead className="border-y border-line bg-sunken text-[12px] text-muted">
                <tr>
                  <th className="px-5 py-2 text-left font-medium">Date</th>
                  <th className="px-3 py-2 text-left font-medium">Type</th>
                  <th className="px-3 py-2 text-left font-medium">Holding</th>
                  <th className="px-3 py-2 text-right font-medium">Units</th>
                  <th className="px-3 py-2 text-right font-medium">Price</th>
                  <th className="px-3 py-2 text-right font-medium">Value</th>
                  <th className="px-3 py-2 text-right font-medium">Cash</th>
                  <th className="w-20 px-3 py-2" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => {
                  const value = r.amount ?? (r.quantity != null && r.price != null ? r.quantity * r.price : null);
                  return (
                    <tr key={r.id} className="group border-b border-line last:border-0">
                      <td className="tabular whitespace-nowrap px-5 py-2.5 text-ink-2">{formatDate(r.trade_date)}</td>
                      <td className="px-3 py-2.5 text-ink">
                        {TXN_LABELS[r.txn_type]}
                        {r.source === "system" && (
                          <Badge tone="warn" className="ml-2 !h-5">
                            Estimated
                          </Badge>
                        )}
                      </td>
                      <td className="px-3 py-2.5 font-medium text-ink">{r.symbol ?? "—"}</td>
                      <td className="tabular px-3 py-2.5 text-right text-ink-2">{r.quantity != null ? formatNumberIN(r.quantity, r.quantity % 1 ? 2 : 0) : "—"}</td>
                      <td className="tabular px-3 py-2.5 text-right text-ink-2">{r.price != null ? <Money value={r.price} decimals={2} /> : "—"}</td>
                      <td className="tabular px-3 py-2.5 text-right text-ink">{value != null ? <Money value={value} /> : "—"}</td>
                      <td className={`tabular px-3 py-2.5 text-right ${r.cash_effect > 0 ? "text-good" : "text-ink-2"}`}>
                        {Math.abs(r.cash_effect) > 0.004 ? (
                          <>
                            {r.cash_effect > 0 ? "+" : "−"}
                            <Money value={Math.abs(r.cash_effect)} />
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <div className="flex justify-end gap-0.5 opacity-70 group-hover:opacity-100">
                          <button
                            onClick={() => {
                              setEditing(r);
                              setFormOpen(true);
                            }}
                            className="sm-icon-btn h-8 w-8"
                            aria-label={`Edit ${TXN_LABELS[r.txn_type]} on ${r.trade_date}`}
                          >
                            <Pencil className="h-3.5 w-3.5" strokeWidth={2} />
                          </button>
                          <button onClick={() => setDeleting(r)} className="sm-icon-btn h-8 w-8 hover:text-bad" aria-label={`Delete ${TXN_LABELS[r.txn_type]} on ${r.trade_date}`}>
                            <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {rows.length > 12 && (
            <button onClick={() => setShowAll((v) => !v)} className="w-full border-t border-line px-5 py-3 text-[13px] font-medium text-muted hover:text-ink">
              {showAll ? "Show fewer" : `Show all ${rows.length}`}
            </button>
          )}
        </>
      )}

      <TransactionModal open={formOpen} onClose={() => setFormOpen(false)} accountId={accountId} existing={editing} symbols={suggestions} onSaved={changed} />
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} accountId={accountId} onImported={changed} />
      <ConfirmModal
        isOpen={deleting !== null}
        title={`Delete this ${deleting ? TXN_LABELS[deleting.txn_type].toLowerCase() : "row"}?`}
        message={
          deleting && Math.abs(deleting.cash_effect) > 0.004
            ? "The holding is worked out again without it, and the cash it moved goes back."
            : "The holding is worked out again without it."
        }
        confirmText="Delete"
        destructive
        onConfirm={remove}
        onCancel={() => setDeleting(null)}
        isProcessing={working}
      />
    </Card>
  );
}
