/**
 * Client-side retirement projection.
 *
 * The same model as backend/database/src/projection.py, which the Retirement
 * agent runs: normally-distributed annual returns per asset class, a 30-year
 * drawdown, and withdrawals that grow with inflation. The assumptions come
 * from the API (GET /api/projection/assumptions) and the random numbers are
 * seeded the same way, so the what-if sliders and the agent's report agree.
 * backend/database/test_projection.py runs both and compares them.
 */

export interface ClassAssumption {
  mean: number;
  std: number;
}

export interface ProjectionAssumptions {
  version: string;
  classes: Record<ClassKey, ClassAssumption>;
  inflation: number;
  retirement_years: number;
  withdrawal_rate: number;
  simulations: number;
  seed: number;
}

export interface ProjectionInput {
  currentValue: number;
  yearsToRetirement: number;
  annualContribution: number;
  targetAnnualIncome: number;
  /** Fractions of total value, e.g. { equity: 0.7, fixed_income: 0.25, cash: 0.05 } */
  allocation: Record<string, number>;
  simulations?: number;
  seed?: number;
}

export interface ProjectionPoint {
  year: number;
  phase: "saving" | "retired";
  p10: number;
  p50: number;
  p90: number;
  /** p10→p90 band as a [low, high] pair for a Recharts range Area */
  band: [number, number];
}

export interface ProjectionResult {
  points: ProjectionPoint[];
  successRate: number;
  medianAtRetirement: number;
  p10AtRetirement: number;
  p90AtRetirement: number;
  expectedAtRetirement: number;
  /** First-year income the median outcome supports at a 4% withdrawal rate */
  sustainableIncome: number;
  expectedReturn: number;
}

// mulberry32 — tiny deterministic PRNG
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(next: () => number) {
  let u = 0;
  while (u === 0) u = next();
  const v = next();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

type ClassKey = "equity" | "fixed_income" | "real_estate" | "commodities" | "cash";
const CLASSES: ClassKey[] = ["equity", "fixed_income", "real_estate", "commodities", "cash"];

/** Normalise an allocation so the modelled classes sum to 1 (unknown classes fold into equity). */
export function modelAllocation(allocation: Record<string, number>): Record<ClassKey, number> {
  const out: Record<ClassKey, number> = { equity: 0, fixed_income: 0, real_estate: 0, commodities: 0, cash: 0 };
  let total = 0;
  for (const [key, value] of Object.entries(allocation)) {
    if (!(value > 0)) continue;
    const k = (CLASSES as string[]).includes(key) ? (key as ClassKey) : "equity";
    out[k] += value;
    total += value;
  }
  if (total <= 0) return { ...out, equity: 0.7, fixed_income: 0.3 };
  for (const k of CLASSES) out[k] /= total;
  return out;
}

export function expectedReturn(allocation: Record<ClassKey, number>, assumptions: ProjectionAssumptions): number {
  return CLASSES.reduce((sum, k) => sum + allocation[k] * assumptions.classes[k].mean, 0);
}

const percentile = (sorted: number[], p: number) => sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];

export function runProjection(input: ProjectionInput, assumptions: ProjectionAssumptions): ProjectionResult {
  const sims = input.simulations ?? assumptions.simulations;
  const years = Math.max(0, Math.round(input.yearsToRetirement));
  const horizon = years + assumptions.retirement_years;
  const alloc = modelAllocation(input.allocation);
  const next = rng(input.seed ?? assumptions.seed);

  const drawReturn = () =>
    CLASSES.reduce((sum, k) => {
      const { mean, std } = assumptions.classes[k];
      return sum + alloc[k] * (std > 0 ? mean + std * gaussian(next) : mean);
    }, 0);

  // paths[t][s] = value of simulation s at the end of year t
  const paths: number[][] = Array.from({ length: horizon + 1 }, () => new Array<number>(sims));
  let successes = 0;

  for (let s = 0; s < sims; s += 1) {
    let value = input.currentValue;
    paths[0][s] = value;

    for (let t = 1; t <= years; t += 1) {
      value = value * (1 + drawReturn()) + input.annualContribution;
      paths[t][s] = value;
    }

    let withdrawal = input.targetAnnualIncome;
    let yearsLasted = 0;
    for (let r = 1; r <= assumptions.retirement_years; r += 1) {
      if (value > 0) {
        withdrawal *= 1 + assumptions.inflation;
        value = value * (1 + drawReturn()) - withdrawal;
        if (value > 0) yearsLasted += 1;
      }
      paths[years + r][s] = Math.max(0, value);
    }
    if (yearsLasted >= assumptions.retirement_years) successes += 1;
  }

  const points: ProjectionPoint[] = paths.map((column, year) => {
    const sorted = [...column].sort((a, b) => a - b);
    const p10 = percentile(sorted, 0.1);
    const p90 = percentile(sorted, 0.9);
    return {
      year,
      phase: year <= years ? "saving" : "retired",
      p10,
      p50: percentile(sorted, 0.5),
      p90,
      band: [p10, p90],
    };
  });

  const mu = expectedReturn(alloc, assumptions);
  let expected = input.currentValue;
  for (let t = 0; t < years; t += 1) expected = expected * (1 + mu) + input.annualContribution;

  const atRetirement = points[years];
  return {
    points,
    successRate: (successes / sims) * 100,
    medianAtRetirement: atRetirement.p50,
    p10AtRetirement: atRetirement.p10,
    p90AtRetirement: atRetirement.p90,
    expectedAtRetirement: expected,
    sustainableIncome: atRetirement.p50 * assumptions.withdrawal_rate,
    expectedReturn: mu,
  };
}
