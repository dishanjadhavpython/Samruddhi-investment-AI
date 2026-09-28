import { ArrowUpRight, Landmark, Plus, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";
import { assetClassColor, CompositionBar, toSlices } from "../components/charts";
import ConfirmModal from "../components/ConfirmModal";
import Layout from "../components/Layout";
import { showToast } from "../components/Toast";
import { AccountTile, Button, Card, EmptyState, Field, Modal, Money, PageHeader, Skeleton, Stat, tileTone } from "../components/ui";
import { formatIndianNumberInput } from "../lib/currency";
import { formatPct } from "../lib/format";
import { useApi } from "../lib/http";
import { ACCOUNT_TYPES, AccountType, rankEntries } from "../lib/portfolio";
import { usePortfolio } from "../lib/portfolio-context";

// Common Indian account types — one tap fills the form
const PRESETS: { name: string; purpose: string; type: AccountType }[] = [
  { name: "EPF", purpose: "Employees' Provident Fund", type: "epf" },
  { name: "PPF", purpose: "Public Provident Fund, 15-year lock-in", type: "ppf" },
  { name: "NPS Tier I", purpose: "National Pension System", type: "nps" },
  { name: "Demat", purpose: "Brokerage account for ETFs and stocks", type: "demat" },
  { name: "Mutual funds", purpose: "SIPs and lump-sum funds", type: "mutual_fund" },
];

const emptyForm: { name: string; purpose: string; cash: string; type: AccountType } = { name: "", purpose: "", cash: "", type: "other" };

export default function Accounts() {
  const router = useRouter();
  const api = useApi();
  const { accounts, metrics, loading, refresh } = usePortfolio();
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [confirm, setConfirm] = useState<{ type: "reset" } | { type: "delete"; id: string; name: string } | null>(null);
  const [working, setWorking] = useState(false);

  // The rail's "+" tile and the command palette link here with ?new=1
  useEffect(() => {
    if (router.query.new === "1") {
      setAddOpen(true);
      router.replace("/accounts", undefined, { shallow: true });
    }
  }, [router]);

  const summaries = useMemo(() => new Map(metrics.accounts.map((a) => [a.id, a])), [metrics.accounts]);

  const accountSlices = useMemo(
    () =>
      accounts
        .map((a, i) => ({ key: a.id, label: a.account_name, value: summaries.get(a.id)?.total ?? 0, color: `var(--series-${tileTone(i)})` }))
        .filter((s) => s.value > 0),
    [accounts, summaries],
  );

  const closeAdd = () => {
    setAddOpen(false);
    setForm(emptyForm);
    setFormError(null);
  };

  const createAccount = async () => {
    if (!form.name.trim()) {
      setFormError("Give the account a name, for example EPF or Demat.");
      return;
    }
    setSaving(true);
    try {
      const created = await api<{ id?: string }>("/api/accounts", {
        method: "POST",
        body: JSON.stringify({
          account_name: form.name.trim(),
          account_purpose: form.purpose.trim() || "Investment account",
          cash_balance: parseFloat(form.cash.replace(/,/g, "")) || 0,
          account_type: form.type,
        }),
      });
      await refresh();
      closeAdd();
      showToast("success", `${form.name.trim()} added.`, created?.id ? { action: { label: "Add holdings", href: `/accounts/${created.id}` } } : undefined);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Couldn't create the account.");
    } finally {
      setSaving(false);
    }
  };

  const loadSample = async () => {
    setSeeding(true);
    try {
      const data = await api<{ message?: string }>("/api/populate-test-data", { method: "POST" });
      await refresh();
      showToast("success", data.message || "Sample portfolio loaded.");
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Couldn't load the sample portfolio.");
    } finally {
      setSeeding(false);
    }
  };

  const runConfirm = async () => {
    if (!confirm) return;
    setWorking(true);
    try {
      if (confirm.type === "reset") {
        const data = await api<{ message?: string }>("/api/reset-accounts", { method: "DELETE" });
        showToast("success", data.message || "All accounts deleted.");
      } else {
        await api(`/api/accounts/${confirm.id}`, { method: "DELETE" });
        showToast("success", `${confirm.name} deleted.`);
      }
      await refresh();
      setConfirm(null);
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "That didn't work — try again.");
    } finally {
      setWorking(false);
    }
  };

  return (
    <Layout title="Accounts">
      <PageHeader
        title="Accounts"
        subtitle="EPF, PPF, NPS, demat — each account, its cash and what's invested inside it."
        actions={
          <>
            {accounts.length > 0 && (
              <Button variant="ghost" onClick={() => setConfirm({ type: "reset" })} icon={<RotateCcw className="h-4 w-4" strokeWidth={2} />}>
                Delete all
              </Button>
            )}
            <Button onClick={() => setAddOpen(true)} icon={<Plus className="h-4 w-4" strokeWidth={2.4} />}>
              Add account
            </Button>
          </>
        }
      />

      {loading && !accounts.length ? (
        <div className="mt-7 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-[240px]" />
          ))}
        </div>
      ) : accounts.length === 0 ? (
        <div className="sm-card mt-7">
          <EmptyState
            icon={<Landmark className="h-5 w-5" strokeWidth={2} />}
            title="No accounts yet"
            body="Add the accounts you invest through. Each one gets its own tile in the left rail so you can jump straight to it."
            action={
              <>
                <Button onClick={() => setAddOpen(true)} icon={<Plus className="h-4 w-4" strokeWidth={2.4} />}>
                  Add account
                </Button>
                <Button variant="secondary" onClick={loadSample} loading={seeding}>
                  Try a sample portfolio
                </Button>
              </>
            }
          />
        </div>
      ) : (
        <>
          <div className="mt-7 grid gap-4 lg:grid-cols-[1fr_1.4fr]">
            <div className="grid grid-cols-2 gap-4">
              <Stat label="Total value" value={<Money value={metrics.totalValue} compact />} />
              <Stat label="Accounts" value={accounts.length} />
              <Stat label="Cash waiting" value={<Money value={metrics.cashValue} compact />} hint={`${formatPct(metrics.totalValue ? (metrics.cashValue / metrics.totalValue) * 100 : 0, 0)} of the total`} />
              <Stat label="Positions" value={accounts.reduce((s, a) => s + a.positions.length, 0)} />
            </div>
            <Card title="Value by account" subtitle="Hover a segment for the amount">
              {accountSlices.length ? <CompositionBar slices={accountSlices} height={18} /> : <p className="text-[13px] text-muted">Add cash or holdings to see the split.</p>}
            </Card>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {accounts.map((account, index) => {
              const s = summaries.get(account.id);
              const classSlices = toSlices(rankEntries(s?.assetClasses ?? {}, 6), (key) => assetClassColor(key));
              const investedPct = s && s.total > 0 ? (s.invested / s.total) * 100 : 0;
              return (
                <article key={account.id} className="sm-card group relative flex flex-col p-5 transition-shadow hover:shadow-[var(--shadow-pop)]">
                  <div className="flex items-start gap-3">
                    <AccountTile name={account.account_name} index={index} size={44} />
                    <div className="min-w-0 flex-1">
                      <h2 className="truncate text-[15px] font-semibold text-ink">
                        <Link href={`/accounts/${account.id}`} className="after:absolute after:inset-0 after:rounded-[18px]">
                          {account.account_name}
                        </Link>
                      </h2>
                      <p className="truncate text-[12.5px] text-muted">{account.account_purpose || "Investment account"}</p>
                    </div>
                    <button
                      onClick={() => setConfirm({ type: "delete", id: account.id, name: account.account_name })}
                      className="sm-icon-btn relative z-10 h-8 w-8 opacity-0 transition-opacity hover:text-bad focus-visible:opacity-100 group-hover:opacity-100"
                      aria-label={`Delete ${account.account_name}`}
                    >
                      <Trash2 className="h-4 w-4" strokeWidth={2} />
                    </button>
                  </div>

                  <p className="mt-5 font-display text-[28px] font-semibold leading-none tracking-[-0.03em] text-ink">
                    <Money value={s?.total ?? account.cash_balance} />
                  </p>

                  <div className="mt-4 flex h-1.5 gap-[2px] overflow-hidden rounded-full">
                    {classSlices.map((c) => (
                      <span key={c.key} style={{ flexGrow: c.value, background: c.color }} className="h-full min-w-[2px]" title={`${c.label}`} />
                    ))}
                    {!classSlices.length && <span className="h-full flex-1 bg-line" />}
                  </div>

                  <dl className="mt-4 grid grid-cols-3 gap-2 text-[12.5px]">
                    <div>
                      <dt className="text-muted">Invested</dt>
                      <dd className="mt-0.5 font-semibold text-ink">
                        <Money value={s?.invested ?? 0} compact />
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted">Cash</dt>
                      <dd className="mt-0.5 font-semibold text-ink">
                        <Money value={account.cash_balance} compact />
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted">Holdings</dt>
                      <dd className="mt-0.5 font-semibold text-ink">{account.positions.length}</dd>
                    </div>
                  </dl>

                  <div className="mt-auto flex items-center justify-between pt-5 text-[12.5px] text-muted">
                    <span>{formatPct(investedPct, 0)} invested</span>
                    <span className="inline-flex items-center gap-1 font-medium text-ink">
                      Open
                      <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={2.2} />
                    </span>
                  </div>
                </article>
              );
            })}
            <button
              onClick={() => setAddOpen(true)}
              className="flex min-h-[220px] flex-col items-center justify-center gap-2 rounded-[18px] border-2 border-dashed border-line-strong text-[13.5px] font-medium text-muted transition-colors hover:border-ink hover:text-ink"
            >
              <Plus className="h-5 w-5" strokeWidth={2} />
              Add another account
            </button>
          </div>
        </>
      )}

      <Modal
        open={addOpen}
        onClose={closeAdd}
        title="Add an account"
        description="You can add holdings to it straight after."
        footer={
          <>
            <Button variant="secondary" onClick={closeAdd}>
              Cancel
            </Button>
            <Button onClick={createAccount} loading={saving}>
              Add account
            </Button>
          </>
        }
      >
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            createAccount();
          }}
        >
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button
                type="button"
                key={p.name}
                onClick={() => setForm((f) => ({ ...f, name: p.name, purpose: p.purpose, type: p.type }))}
                className={`h-7 rounded-full px-2.5 text-[12px] font-medium transition-colors ${
                  form.name === p.name ? "bg-accent text-accent-ink" : "bg-sunken text-ink-2 hover:text-ink"
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
          <Field label="Account name" htmlFor="acc-name" error={formError}>
            <input id="acc-name" className="sm-field" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="EPF, PPF, Demat…" />
          </Field>
          <Field label="Account type" htmlFor="acc-type" hint="Only cash in demat accounts counts as cash waiting to be invested.">
            <select id="acc-type" className="sm-field" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value as AccountType })}>
              {ACCOUNT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="What it's for" htmlFor="acc-purpose">
            <input id="acc-purpose" className="sm-field" value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} placeholder="Long-term growth, retirement…" />
          </Field>
          <Field label="Cash balance" htmlFor="acc-cash" hint="Uninvested money sitting in this account.">
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">₹</span>
              <input
                id="acc-cash"
                inputMode="decimal"
                className="sm-field pl-7"
                value={form.cash}
                onChange={(e) => setForm({ ...form, cash: formatIndianNumberInput(e.target.value) })}
                placeholder="0"
              />
            </div>
          </Field>
          <button type="submit" hidden />
        </form>
      </Modal>

      <ConfirmModal
        isOpen={confirm !== null}
        title={confirm?.type === "reset" ? "Delete all accounts?" : `Delete ${confirm?.type === "delete" ? confirm.name : "account"}?`}
        message={
          confirm?.type === "reset"
            ? `This permanently removes all ${accounts.length} accounts and every holding inside them. Past reports stay.`
            : "This permanently removes the account and every holding inside it. Past reports stay."
        }
        confirmText={confirm?.type === "reset" ? "Delete all accounts" : "Delete account"}
        destructive
        onConfirm={runConfirm}
        onCancel={() => setConfirm(null)}
        isProcessing={working}
      />
    </Layout>
  );
}
