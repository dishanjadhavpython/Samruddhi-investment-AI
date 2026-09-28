import { Check, ChevronLeft, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";
import { assetClassColor, DonutWithLegend, toSlices } from "../../components/charts";
import ConfirmModal from "../../components/ConfirmModal";
import Layout from "../../components/Layout";
import { CalmToggle, DayChange, PriceStamp } from "../../components/PriceStamp";
import { showToast } from "../../components/Toast";
import { TransactionsCard } from "../../components/Transactions";
import { AccountTile, Badge, Button, Card, EmptyState, Field, Modal, Money, Skeleton, Stat } from "../../components/ui";
import { formatINR, formatIndianNumberInput, formatNumberIN } from "../../lib/currency";
import { formatPct, formatSignedPct, labelize } from "../../lib/format";
import { useApi } from "../../lib/http";
import { ACCOUNT_TYPES, AccountType, accountTypeLabel, positionValue, rankEntries } from "../../lib/portfolio";
import { usePortfolio } from "../../lib/portfolio-context";

interface CatalogItem {
  symbol: string;
  name: string;
  instrument_type: string;
  current_price: number | null;
  price_as_of?: string | null;
  price_source?: string | null;
  price_status?: string | null;
}

function AddHoldingModal({ open, onClose, accountId, onAdded }: { open: boolean; onClose: () => void; accountId: string; onAdded: () => Promise<void> }) {
  const api = useApi();
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<CatalogItem | null>(null);
  const [quantity, setQuantity] = useState("");
  const [cursor, setCursor] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || catalog.length) return;
    api<CatalogItem[]>("/api/instruments")
      .then((rows) => setCatalog(Array.isArray(rows) ? rows : []))
      .catch(() => setCatalog([]));
  }, [open, catalog.length, api]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return catalog.slice(0, 6);
    return catalog.filter((i) => i.symbol.toLowerCase().includes(q) || i.name.toLowerCase().includes(q)).slice(0, 6);
  }, [catalog, query]);

  const reset = () => {
    setQuery("");
    setPicked(null);
    setQuantity("");
    setError(null);
    setCursor(0);
  };

  const close = () => {
    reset();
    onClose();
  };

  const symbol = (picked?.symbol ?? query).trim().toUpperCase();
  const qty = parseFloat(quantity);
  const preview = picked?.current_price != null && qty > 0 ? picked.current_price * qty : null;

  const submit = async () => {
    if (!symbol) return setError("Pick an instrument or type its symbol.");
    if (!(qty > 0)) return setError("Enter how many units you hold.");
    setSaving(true);
    try {
      await api("/api/positions", { method: "POST", body: JSON.stringify({ account_id: accountId, symbol, quantity: qty }) });
      await onAdded();
      showToast("success", `${symbol} added.`);
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add the holding.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Add a holding"
      description="Search the catalogue, or type any NSE symbol — new ones are classified by the Tagger agent on your next analysis."
      width="max-w-lg"
      footer={
        <>
          <Button variant="secondary" onClick={close}>
            Cancel
          </Button>
          <Button onClick={submit} loading={saving}>
            Add holding
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {picked ? (
          <div className="flex items-center gap-3 rounded-xl border border-line bg-sunken px-3.5 py-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-accent text-[12px] font-bold text-accent-ink">{picked.symbol.slice(0, 2)}</span>
            <span className="min-w-0 flex-1">
              <span className="block text-[14px] font-semibold text-ink">{picked.symbol}</span>
              <span className="block truncate text-[12.5px] text-muted">{picked.name}</span>
            </span>
            <button onClick={() => setPicked(null)} className="sm-icon-btn h-8 w-8" aria-label="Choose a different instrument">
              <X className="h-4 w-4" strokeWidth={2} />
            </button>
          </div>
        ) : (
          <Field label="Instrument" htmlFor="h-search">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" strokeWidth={2} />
              <input
                id="h-search"
                className="sm-field pl-9 uppercase placeholder:normal-case"
                placeholder="NIFTYBEES, gold, liquid fund…"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setCursor(0);
                }}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setCursor((c) => Math.min(matches.length - 1, c + 1));
                  } else if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setCursor((c) => Math.max(0, c - 1));
                  } else if (e.key === "Enter" && matches[cursor]) {
                    e.preventDefault();
                    setPicked(matches[cursor]);
                  }
                }}
                role="combobox"
                aria-expanded={matches.length > 0}
                aria-controls="h-options"
                autoComplete="off"
              />
            </div>
            <ul id="h-options" role="listbox" className="mt-2 max-h-[240px] overflow-y-auto rounded-xl border border-line">
              {matches.map((item, i) => (
                <li key={item.symbol} role="option" aria-selected={i === cursor}>
                  <button
                    type="button"
                    onMouseMove={() => setCursor(i)}
                    onClick={() => setPicked(item)}
                    className={`flex w-full items-center gap-3 px-3 py-2.5 text-left ${i === cursor ? "bg-sunken" : ""}`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-semibold text-ink">{item.symbol}</span>
                      <span className="block truncate text-[12px] text-muted">
                        {item.name}
                        {item.instrument_type && `, ${labelize(item.instrument_type)}`}
                      </span>
                    </span>
                    {item.current_price != null && (
                      <span className="shrink-0 text-right">
                        <Money value={item.current_price} decimals={2} className="tabular block text-[12.5px] text-ink-2" />
                        <PriceStamp instrument={item} className="justify-end" />
                      </span>
                    )}
                  </button>
                </li>
              ))}
              {matches.length === 0 && (
                <li className="px-3 py-3 text-[12.5px] text-muted">
                  Not in the catalogue. We&apos;ll add <span className="font-semibold text-ink">{symbol || "it"}</span> and price it on the next run.
                </li>
              )}
            </ul>
          </Field>
        )}

        <Field label="Units held" htmlFor="h-qty" error={error}>
          <input id="h-qty" className="sm-field" inputMode="decimal" type="number" min="0" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} placeholder="0" />
        </Field>

        {preview != null && (
          <p className="rounded-xl bg-accent-soft px-3.5 py-3 text-[13px] text-ink">
            {formatNumberIN(qty, qty % 1 ? 2 : 0)} × {formatINR(picked?.current_price ?? 0)} ={" "}
            <Money value={preview} decimals={2} className="font-semibold" />
            <PriceStamp instrument={picked} className="mt-1" />
          </p>
        )}
      </div>
    </Modal>
  );
}

export default function AccountDetail() {
  const router = useRouter();
  const api = useApi();
  const { accounts, metrics, loading, refresh } = usePortfolio();
  const id = typeof router.query.id === "string" ? router.query.id : "";
  const index = accounts.findIndex((a) => a.id === id);
  const account = index >= 0 ? accounts[index] : null;
  const summary = metrics.accounts.find((a) => a.id === id);

  const [editOpen, setEditOpen] = useState(false);
  const [edit, setEdit] = useState<{ name: string; purpose: string; cash: string; type: AccountType }>({ name: "", purpose: "", cash: "", type: "other" });
  const [savingAccount, setSavingAccount] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [editingRow, setEditingRow] = useState<string | null>(null);
  const [rowQty, setRowQty] = useState("");
  const [rowSaving, setRowSaving] = useState(false);
  const [confirm, setConfirm] = useState<{ kind: "position"; id: string; symbol: string } | { kind: "account" } | null>(null);
  const [working, setWorking] = useState(false);

  const openEdit = () => {
    if (!account) return;
    setEdit({ name: account.account_name, purpose: account.account_purpose, cash: formatNumberIN(account.cash_balance), type: account.account_type });
    setEditOpen(true);
  };

  const saveAccount = async () => {
    if (!edit.name.trim()) return;
    setSavingAccount(true);
    try {
      await api(`/api/accounts/${id}`, {
        method: "PUT",
        body: JSON.stringify({
          account_name: edit.name.trim(),
          account_purpose: edit.purpose.trim(),
          cash_balance: parseFloat(edit.cash.replace(/,/g, "")) || 0,
          account_type: edit.type,
        }),
      });
      await refresh();
      setEditOpen(false);
      showToast("success", "Account saved.");
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Couldn't save the account.");
    } finally {
      setSavingAccount(false);
    }
  };

  const saveRow = async (positionId: string) => {
    const quantity = parseFloat(rowQty);
    if (!(quantity >= 0)) {
      showToast("error", "Enter a quantity of zero or more.");
      return;
    }
    setRowSaving(true);
    try {
      await api(`/api/positions/${positionId}`, { method: "PUT", body: JSON.stringify({ quantity }) });
      await refresh();
      setEditingRow(null);
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Couldn't update the holding.");
    } finally {
      setRowSaving(false);
    }
  };

  const runConfirm = async () => {
    if (!confirm) return;
    setWorking(true);
    try {
      if (confirm.kind === "position") {
        await api(`/api/positions/${confirm.id}`, { method: "DELETE" });
        await refresh();
        showToast("success", `${confirm.symbol} removed.`);
      } else {
        await api(`/api/accounts/${id}`, { method: "DELETE" });
        await refresh();
        showToast("success", "Account deleted.");
        router.push("/accounts");
      }
      setConfirm(null);
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "That didn't work — try again.");
    } finally {
      setWorking(false);
    }
  };

  const positions = useMemo(() => [...(account?.positions ?? [])].sort((a, b) => positionValue(b) - positionValue(a)), [account]);
  const classSlices = useMemo(() => toSlices(rankEntries(summary?.assetClasses ?? {}, 6), (k) => assetClassColor(k)), [summary]);
  const invested = summary?.invested ?? 0;

  if (!account) {
    return (
      <Layout title="Account">
        {loading ? (
          <div className="space-y-4">
            <Skeleton className="h-16 w-1/2" />
            <Skeleton className="h-[360px]" />
          </div>
        ) : (
          <div className="sm-card">
            <EmptyState title="Account not found" body="It may have been deleted, or the link is out of date." action={<Link href="/accounts" className="sm-btn sm-btn-primary">Back to accounts</Link>} />
          </div>
        )}
      </Layout>
    );
  }

  return (
    <Layout title={account.account_name}>
      <Link href="/accounts" className="inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-ink">
        <ChevronLeft className="h-4 w-4" strokeWidth={2} />
        Accounts
      </Link>

      <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <AccountTile name={account.account_name} index={index} size={56} />
          <div className="min-w-0">
            <h1 className="font-display text-[28px] font-semibold leading-tight tracking-[-0.03em] text-ink">{account.account_name}</h1>
            <p className="flex flex-wrap items-center gap-2 text-[14px] text-muted">
              <Badge>{accountTypeLabel(account.account_type)}</Badge>
              {account.account_purpose || "Investment account"}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={() => setConfirm({ kind: "account" })} icon={<Trash2 className="h-4 w-4" strokeWidth={2} />}>
            Delete
          </Button>
          <Button variant="secondary" onClick={openEdit} icon={<Pencil className="h-4 w-4" strokeWidth={2} />}>
            Edit account
          </Button>
          <Button onClick={() => setAddOpen(true)} icon={<Plus className="h-4 w-4" strokeWidth={2.4} />}>
            Add holding
          </Button>
        </div>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Total value" value={<Money value={summary?.total ?? account.cash_balance} compact />} />
        <Stat label="Invested" value={<Money value={invested} compact />} />
        <Stat label="Cash" value={<Money value={account.cash_balance} compact />} hint="Edit to update after a deposit" />
        <Stat label="Holdings" value={positions.length} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-12">
        <section className="sm-card overflow-hidden lg:col-span-8">
          <header className="flex items-center justify-between px-5 pb-3 pt-4">
            <h2 className="text-[13.5px] font-semibold text-ink">Holdings</h2>
            <div className="flex items-center gap-3">
              <p className="hidden text-[12.5px] text-muted sm:block">Change quantities by recording transactions below</p>
              {positions.length > 0 && <CalmToggle />}
            </div>
          </header>
          {positions.length === 0 ? (
            <EmptyState
              title="Nothing invested here yet"
              body="Add the ETFs, funds or stocks this account holds."
              action={
                <Button onClick={() => setAddOpen(true)} icon={<Plus className="h-4 w-4" strokeWidth={2.4} />}>
                  Add holding
                </Button>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[700px] text-[13.5px]">
                <thead className="border-y border-line bg-sunken text-[12.5px] text-muted">
                  <tr>
                    <th className="px-5 py-2.5 text-left font-medium">Holding</th>
                    <th className="px-4 py-2.5 text-right font-medium">Units</th>
                    <th className="px-4 py-2.5 text-right font-medium">Price</th>
                    <th className="px-4 py-2.5 text-right font-medium">Value</th>
                    <th className="px-4 py-2.5 text-right font-medium">Cost</th>
                    <th className="px-4 py-2.5 text-right font-medium">Share</th>
                    <th className="w-12 px-3 py-2.5" aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => {
                    const value = positionValue(p);
                    const editing = editingRow === p.id;
                    const cls = p.instrument ? Object.entries(p.instrument.allocation_asset_class).sort((a, b) => b[1] - a[1])[0]?.[0] : undefined;
                    return (
                      <tr key={p.id} className="group border-b border-line last:border-0">
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-3">
                            <span className="h-8 w-1.5 shrink-0 rounded-full" style={{ background: assetClassColor(cls ?? "unclassified") }} aria-hidden="true" />
                            <div className="min-w-0">
                              <p className="font-semibold text-ink">{p.symbol}</p>
                              <p className="max-w-[240px] truncate text-[12.5px] text-muted">{p.instrument?.name ?? "Awaiting classification"}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right">
                          {editing ? (
                            <form
                              className="ml-auto flex w-[150px] items-center gap-1"
                              onSubmit={(e) => {
                                e.preventDefault();
                                saveRow(p.id);
                              }}
                            >
                              <input
                                autoFocus
                                type="number"
                                step="any"
                                min="0"
                                value={rowQty}
                                onChange={(e) => setRowQty(e.target.value)}
                                onKeyDown={(e) => e.key === "Escape" && setEditingRow(null)}
                                className="sm-field !h-8 !px-2 text-right"
                                aria-label={`Units of ${p.symbol}`}
                              />
                              <button type="submit" disabled={rowSaving} className="sm-icon-btn h-8 w-8 shrink-0 text-good" aria-label="Save">
                                <Check className="h-4 w-4" strokeWidth={2.4} />
                              </button>
                            </form>
                          ) : (
                            <button
                              onClick={() => {
                                setEditingRow(p.id);
                                setRowQty(String(p.quantity));
                              }}
                              className="tabular rounded-md px-1.5 py-0.5 text-ink-2 underline decoration-line-strong decoration-dotted underline-offset-4 hover:bg-sunken hover:text-ink"
                            >
                              {formatNumberIN(p.quantity, p.quantity % 1 ? 2 : 0)}
                            </button>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right text-ink-2">
                          {p.price != null ? <Money value={p.price} decimals={2} /> : <span className="text-warn">No price</span>}
                          <PriceStamp instrument={p.instrument} className="mt-0.5 flex justify-end" />
                        </td>
                        <td className="px-4 py-3 text-right font-semibold text-ink">
                          <Money value={value} />
                          <DayChange instrument={p.instrument} quantity={p.quantity} className="mt-0.5 block font-normal" />
                        </td>
                        <td className="px-4 py-3 text-right text-ink-2">
                          {p.cost_basis != null ? (
                            <>
                              <Money value={p.cost_basis} />
                              {p.cost_basis > 0 && p.price != null && (
                                <span className={`tabular mt-0.5 block text-[12px] ${value >= p.cost_basis ? "text-good" : "text-bad"}`}>
                                  {formatSignedPct(((value - p.cost_basis) / p.cost_basis) * 100, 1)}
                                </span>
                              )}
                            </>
                          ) : (
                            <span className="text-[12.5px] text-muted" title="The opening balance has no price. Edit it under Transactions.">
                              Unknown
                            </span>
                          )}
                        </td>
                        <td className="tabular px-4 py-3 text-right text-ink-2">{formatPct(invested ? (value / invested) * 100 : 0, 1)}</td>
                        <td className="px-3 py-3 text-right">
                          <button
                            onClick={() => setConfirm({ kind: "position", id: p.id, symbol: p.symbol })}
                            className="sm-icon-btn h-8 w-8 opacity-60 hover:text-bad group-hover:opacity-100"
                            aria-label={`Remove ${p.symbol}`}
                          >
                            <Trash2 className="h-4 w-4" strokeWidth={2} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <Card title="Inside this account" subtitle="By asset class, including cash" className="lg:col-span-4">
          {classSlices.length ? (
            <DonutWithLegend
              slices={classSlices}
              size={150}
              center={
                <>
                  <span className="font-display text-[20px] font-semibold leading-none text-ink">{formatPct(summary && summary.total ? (invested / summary.total) * 100 : 0, 0)}</span>
                  <span className="mt-1 text-[11.5px] text-muted">invested</span>
                </>
              }
            />
          ) : (
            <p className="text-[13px] text-muted">Add cash or holdings to see the mix.</p>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <TransactionsCard accountId={id} symbols={positions.map((p) => p.symbol)} onChanged={refresh} />
      </div>

      <AddHoldingModal open={addOpen} onClose={() => setAddOpen(false)} accountId={id} onAdded={refresh} />

      <Modal
        open={editOpen}
        onClose={() => setEditOpen(false)}
        title="Edit account"
        footer={
          <>
            <Button variant="secondary" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button onClick={saveAccount} loading={savingAccount} disabled={!edit.name.trim()}>
              Save changes
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Account name" htmlFor="e-name">
            <input id="e-name" className="sm-field" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
          </Field>
          <Field label="Account type" htmlFor="e-type" hint="Only cash in demat accounts counts as cash waiting to be invested.">
            <select id="e-type" className="sm-field" value={edit.type} onChange={(e) => setEdit({ ...edit, type: e.target.value as AccountType })}>
              {ACCOUNT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="What it's for" htmlFor="e-purpose">
            <input id="e-purpose" className="sm-field" value={edit.purpose} onChange={(e) => setEdit({ ...edit, purpose: e.target.value })} />
          </Field>
          <Field label="Cash balance" htmlFor="e-cash">
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">₹</span>
              <input id="e-cash" inputMode="decimal" className="sm-field pl-7" value={edit.cash} onChange={(e) => setEdit({ ...edit, cash: formatIndianNumberInput(e.target.value) })} />
            </div>
          </Field>
        </div>
      </Modal>

      <ConfirmModal
        isOpen={confirm !== null}
        title={confirm?.kind === "position" ? `Remove ${confirm.symbol}?` : `Delete ${account.account_name}?`}
        message={
          confirm?.kind === "position"
            ? "The holding and its recorded transactions are removed from this account. Cash they moved stays where it is."
            : "This permanently removes the account, every holding inside it and their transactions. Past reports stay."
        }
        confirmText={confirm?.kind === "position" ? "Remove holding" : "Delete account"}
        destructive
        onConfirm={runConfirm}
        onCancel={() => setConfirm(null)}
        isProcessing={working}
      />
    </Layout>
  );
}
