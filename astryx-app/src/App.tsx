// Astryx (Meta design system) front-end demo for the Lindström KAM
// Customer Value & Sustainability Review. Re-presents the numbers computed
// by this repo's own deterministic pipeline (pipeline.run_all on the
// synthetic sample pack). Original Streamlit app and Lovable app untouched.

import {useEffect, useMemo, useState} from 'react';
import {VStack, HStack, Layout, LayoutContent} from '@astryxdesign/core/Layout';
import {Text, Heading} from '@astryxdesign/core/Text';
import {Card} from '@astryxdesign/core/Card';
import {Button} from '@astryxdesign/core/Button';
import {Badge} from '@astryxdesign/core/Badge';
import {Banner} from '@astryxdesign/core/Banner';
import {TabList, Tab} from '@astryxdesign/core/TabList';
import {Selector} from '@astryxdesign/core/Selector';
import {Table, pixel, proportional} from '@astryxdesign/core/Table';
import type {TableColumn} from '@astryxdesign/core/Table';
import {Grid} from '@astryxdesign/core/Grid';
import {Divider} from '@astryxdesign/core/Divider';
import {Spinner} from '@astryxdesign/core/Spinner';
import {Markdown} from '@astryxdesign/core/Markdown';
import {List, ListItem} from '@astryxdesign/core/List';
import {Icon} from '@astryxdesign/core/Icon';
import {
  BarChart,
  Bar,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import {StopIcon} from '@heroicons/react/24/solid';

// ------------------------------------------------------------------ types

interface Customer {
  id: string;
  name: string;
  industry: string;
  segment: string;
  topics: string[];
}

interface PortfolioRow extends Record<string, unknown> {
  customerId: string;
  customer: string;
  industry: string;
  segment: string;
  sites: number;
  countries: string;
  kg: number | null;
  utilisation: number | null;
  ontime: number | null;
  requestsPer1000: number | null;
  repairsPer100: number | null;
  sitesAttention: number;
  waterSaving: number | null;
  waterLow: number | null;
  waterHigh: number | null;
  co2Saving: number | null;
  shareKg: number | null;
}

interface SiteRow extends Record<string, unknown> {
  siteId: string;
  site: string;
  customerId: string;
  customer: string;
  country: string;
  type: string;
  kg: number | null;
  utilisation: number | null;
  ontime: number | null;
  requests: number | null;
  repairs: number | null;
  recyclingPct: number | null;
  attention: boolean;
  nFlags: number;
}

interface IssueRow extends Record<string, unknown> {
  severity: string;
  check: string;
  table: string;
  location: string;
  explanation: string;
  fix: string;
}

interface MetricItem {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  theme: string;
  status: string;
  formula: string;
  note: string;
  low: number | null;
  high: number | null;
  caveat: string;
  inputStatus: string;
}

interface Opportunity {
  id: string;
  theme: string;
  title: string;
  hypothesis: string;
  sizing: string;
  status: string;
  evidence: string[] | string;
  assumptions: string[] | string;
  confirm: string[] | string;
  caveat: string;
}

interface PerCustomer {
  metrics: MetricItem[];
  monthly: {month: string; kg: number | null; requests: number | null; utilisation: number | null; repairs: number | null}[];
  opportunities: Opportunity[];
  recommendations: {theme: string; title: string; text: string; basis: string}[];
  narrative: string;
}

interface DemoData {
  generatedFrom: string;
  customers: Customer[];
  portfolio: PortfolioRow[];
  sites: SiteRow[];
  issues: IssueRow[];
  perCustomer: Record<string, PerCustomer>;
}

// ------------------------------------------------------------------ helpers

const colors = {
  blue: 'var(--color-data-categorical-blue, #0171E3)',
  orange: 'var(--color-data-categorical-orange, #EB6E00)',
  green: 'var(--color-data-categorical-green, #0B991F)',
  purple: 'var(--color-data-categorical-purple, #6B1EFD)',
  neutral: 'var(--color-data-neutral, #8494A3)',
};

const tickStyle = {
  fontSize: 'var(--font-size-sm, 12px)',
  fill: 'var(--color-text-secondary, #4E606F)',
} as const;

function fmt(v: number | null, unit = ''): string {
  if (v == null) return 'n/a';
  const abs = Math.abs(v);
  let s: string;
  if (abs >= 1_000_000) s = `${(v / 1_000_000).toFixed(2)} M`;
  else if (abs >= 10_000) s = `${(v / 1_000).toFixed(1)} k`;
  else s = v.toLocaleString(undefined, {maximumFractionDigits: 1});
  return unit ? `${s} ${unit}` : s;
}

function statusVariant(status: string): 'success' | 'warning' | 'neutral' {
  if (status === 'CALCULATED') return 'success';
  if (status === 'ALLOCATED') return 'warning';
  return 'neutral';
}

function severityVariant(sev: string): 'error' | 'warning' | 'info' | 'neutral' {
  const s = sev.toLowerCase();
  if (s.includes('high') || s.includes('error') || s.includes('critical')) return 'error';
  if (s.includes('medium') || s.includes('warn')) return 'warning';
  if (s.includes('low') || s.includes('info')) return 'info';
  return 'neutral';
}

function asList(v: string[] | string): string[] {
  return Array.isArray(v) ? v : v ? [v] : [];
}

function LegendItem({color, label}: {color: string; label: string}) {
  return (
    <HStack gap={2} vAlign="center">
      <Icon icon={StopIcon} size="xsm" style={{color}} />
      <Text type="supporting" color="secondary">
        {label}
      </Text>
    </HStack>
  );
}

function StatCard({label, value, note}: {label: string; value: string; note?: string}) {
  return (
    <Card>
      <VStack gap={2}>
        <Heading level={4}>{label}</Heading>
        <Heading level={2}>{value}</Heading>
        {note ? (
          <Text type="supporting" color="secondary">
            {note}
          </Text>
        ) : null}
      </VStack>
    </Card>
  );
}

// ------------------------------------------------------------------ portfolio tab

const siteColumns: TableColumn<SiteRow>[] = [
  {key: 'site', header: 'Site', width: proportional(1.4)},
  {key: 'customer', header: 'Customer', width: proportional(1.2)},
  {key: 'country', header: 'Country', width: pixel(110)},
  {
    key: 'kg',
    header: 'Kg washed',
    width: pixel(100),
    renderCell: s => fmt(s.kg),
  },
  {
    key: 'utilisation',
    header: 'Utilisation',
    width: pixel(100),
    renderCell: s => (s.utilisation == null ? 'n/a' : `${s.utilisation.toFixed(1)}%`),
  },
  {
    key: 'ontime',
    header: 'On-time',
    width: pixel(90),
    renderCell: s => (s.ontime == null ? 'n/a' : `${s.ontime.toFixed(1)}%`),
  },
  {
    key: 'attention',
    header: 'Attention',
    width: pixel(110),
    renderCell: s =>
      s.attention ? <Badge variant="warning" label={`${s.nFlags} signals`} /> : <Badge variant="neutral" label="ok" />,
  },
];

function PortfolioTab({data, onOpenCustomer}: {data: DemoData; onOpenCustomer: (cid: string) => void}) {
  const shareData = data.portfolio.map(p => ({name: p.customer, share: p.shareKg ?? 0}));
  return (
    <VStack gap={6}>
      <Grid columns={{minWidth: 320, repeat: 'fit'}} gap={4}>
        {data.portfolio.map(p => (
          <Card key={p.customerId}>
            <VStack gap={3}>
              <HStack hAlign="between" vAlign="center">
                <Heading level={3}>{p.customer}</Heading>
                {p.sitesAttention > 0 ? (
                  <Badge variant="warning" label={`${p.sitesAttention} sites need attention`} />
                ) : (
                  <Badge variant="success" label="on track" />
                )}
              </HStack>
              <HStack gap={2}>
                <Badge variant="blue" label={p.industry} />
                <Badge variant="neutral" label={p.segment} />
              </HStack>
              <Text type="supporting" color="secondary">
                {p.sites} sites - {p.countries}
              </Text>
              <Divider />
              <VStack gap={1}>
                <Text type="body">Textiles washed: {fmt(p.kg, 'kg')}</Text>
                <Text type="body">
                  Utilisation {p.utilisation?.toFixed(1)}% - on-time {p.ontime?.toFixed(1)}%
                </Text>
                <Text type="body">
                  Water saving {fmt(p.waterSaving, 'L')} (range {fmt(p.waterLow)} - {fmt(p.waterHigh)})
                </Text>
                <Text type="body">CO2e saving {fmt(p.co2Saving, 'kg')}</Text>
              </VStack>
              <Button label="Open customer" variant="secondary" onClick={() => onOpenCustomer(p.customerId)} />
            </VStack>
          </Card>
        ))}
      </Grid>
      <Card>
        <VStack gap={3}>
          <Heading level={3}>Share of portfolio (kg washed)</Heading>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={shareData} margin={{top: 5, right: 10, left: 0, bottom: 5}}>
              <CartesianGrid horizontal vertical={false} stroke="var(--color-border, rgba(5,54,89,0.1))" />
              <XAxis dataKey="name" tick={tickStyle} axisLine={false} tickLine={false} />
              <YAxis tick={tickStyle} axisLine={false} tickLine={false} width={40} unit="%" />
              <Tooltip />
              <Bar dataKey="share" name="Share of kg" fill={colors.blue} isAnimationActive={false} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </VStack>
      </Card>
      <Card>
        <VStack gap={4}>
          <Heading level={3}>All sites ({data.sites.length})</Heading>
          <Table<SiteRow>
            data={data.sites.map(s => ({...s, id: s.siteId}))}
            columns={siteColumns}
            idKey="id"
            density="compact"
            dividers="rows"
            hasHover
          />
        </VStack>
      </Card>
    </VStack>
  );
}

// ------------------------------------------------------------------ customer tab

function CustomerTab({data, customerId, onChange}: {data: DemoData; customerId: string; onChange: (cid: string) => void}) {
  const c = data.customers.find(x => x.id === customerId) ?? data.customers[0];
  const pc = data.perCustomer[c.id];
  const p = data.portfolio.find(x => x.customerId === c.id);
  const sites = data.sites.filter(s => s.customerId === c.id);
  const byKey = Object.fromEntries(pc.metrics.map(m => [m.key, m]));
  const get = (k: string) => byKey[k];

  const metricRows = pc.metrics.map(m => ({...m, id: m.key}));
  const metricColumns: TableColumn<(typeof metricRows)[number]>[] = [
    {key: 'label', header: 'Metric', width: proportional(1.6)},
    {
      key: 'value',
      header: 'Value',
      width: pixel(130),
      renderCell: m => `${fmt(m.value)} ${m.unit}`.trim(),
    },
    {
      key: 'range',
      header: 'Low - High',
      width: pixel(160),
      renderCell: m =>
        m.low != null && m.high != null && (m.low !== m.value || m.high !== m.value)
          ? `${fmt(m.low)} - ${fmt(m.high)}`
          : '-',
    },
    {
      key: 'status',
      header: 'Status',
      width: pixel(120),
      renderCell: m => <Badge variant={statusVariant(m.status)} label={m.status} />,
    },
    {
      key: 'formula',
      header: 'How it is calculated',
      width: proportional(2),
      renderCell: m => (
        <VStack gap={0}>
          <Text type="supporting" color="secondary">
            {m.formula}
          </Text>
          {m.note ? (
            <Text type="supporting" color="secondary">
              {m.note}
            </Text>
          ) : null}
        </VStack>
      ),
    },
  ];

  const monthly = pc.monthly;
  return (
    <VStack gap={6}>
      <HStack gap={4} vAlign="end" wrap="wrap">
        <Selector
          label="Customer"
          options={data.customers.map(x => ({value: x.id, label: x.name}))}
          value={c.id}
          onChange={onChange}
          width={320}
        />
        <HStack gap={2}>
          <Badge variant="blue" label={c.industry} />
          <Badge variant="neutral" label={c.segment} />
          {c.topics.map(t => (
            <Badge key={t} variant="purple" label={t} />
          ))}
        </HStack>
      </HStack>
      <Grid columns={{minWidth: 200, repeat: 'fit'}} gap={4}>
        <StatCard label="Textiles washed" value={fmt(get('kg')?.value ?? null, 'kg')} note="review period" />
        <StatCard
          label="Garment utilisation"
          value={get('utilisation')?.value != null ? `${get('utilisation')!.value!.toFixed(1)}%` : 'n/a'}
          note="scanned / allocated, last month"
        />
        <StatCard
          label="On-time cycles"
          value={p?.ontime != null ? `${p.ontime.toFixed(1)}%` : 'n/a'}
          note="service cycles"
        />
        <StatCard label="Active wearers" value={fmt(get('wearers')?.value ?? null)} note="may double-count (pack caveat)" />
        <StatCard label="Service requests" value={fmt(get('requests')?.value ?? null)} />
        <StatCard label="Delivery sites" value={fmt(get('sites')?.value ?? null)} />
      </Grid>
      <Card>
        <VStack gap={3}>
          <Heading level={3}>Monthly trend</Heading>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={monthly} margin={{top: 5, right: 10, left: 0, bottom: 5}}>
              <CartesianGrid horizontal vertical={false} stroke="var(--color-border, rgba(5,54,89,0.1))" />
              <XAxis dataKey="month" tick={tickStyle} axisLine={false} tickLine={false} />
              <YAxis yAxisId="kg" tick={tickStyle} axisLine={false} tickLine={false} width={56} />
              <YAxis yAxisId="util" orientation="right" domain={[0, 100]} tick={tickStyle} axisLine={false} tickLine={false} width={40} unit="%" />
              <Tooltip />
              <Bar yAxisId="kg" dataKey="kg" name="Kg washed" fill={colors.blue} isAnimationActive={false} radius={[4, 4, 0, 0]} />
              <Line yAxisId="util" type="linear" dataKey="utilisation" name="Utilisation %" stroke={colors.orange} strokeWidth={2} dot={false} />
              <Line yAxisId="kg" type="linear" dataKey="repairs" name="Repairs" stroke={colors.purple} strokeWidth={1.5} strokeDasharray="5 3" dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
          <HStack gap={6}>
            <LegendItem color={colors.blue} label="Kg washed" />
            <LegendItem color={colors.orange} label="Utilisation %" />
            <LegendItem color={colors.purple} label="Repairs" />
          </HStack>
        </VStack>
      </Card>
      <Card>
        <VStack gap={4}>
          <Heading level={3}>Value delivered, with status and formula</Heading>
          <Text type="supporting" color="secondary">
            Every number comes from the repo's deterministic metric engine (no LLM): status says how
            the number was produced; the formula is shown for each.
          </Text>
          <Table data={metricRows} columns={metricColumns} idKey="id" density="compact" dividers="rows" hasHover />
        </VStack>
      </Card>
      <Card>
        <VStack gap={4}>
          <Heading level={3}>Sites ({sites.length})</Heading>
          <Table<SiteRow>
            data={sites.map(s => ({...s, id: s.siteId}))}
            columns={siteColumns}
            idKey="id"
            density="compact"
            dividers="rows"
            hasHover
          />
        </VStack>
      </Card>
    </VStack>
  );
}

// ------------------------------------------------------------------ meeting brief tab

function MeetingBriefTab({data, customerId, onChange}: {data: DemoData; customerId: string; onChange: (cid: string) => void}) {
  const c = data.customers.find(x => x.id === customerId) ?? data.customers[0];
  const pc = data.perCustomer[c.id];
  return (
    <VStack gap={6}>
      <Selector
        label="Customer"
        options={data.customers.map(x => ({value: x.id, label: x.name}))}
        value={c.id}
        onChange={onChange}
        width={320}
      />
      {pc.narrative ? (
        <Card>
          <VStack gap={3}>
            <Heading level={3}>Account story</Heading>
            <Markdown>{pc.narrative}</Markdown>
          </VStack>
        </Card>
      ) : null}
      <Heading level={3}>Ranked discussion topics</Heading>
      <Grid columns={{minWidth: 340, repeat: 'fit'}} gap={4}>
        {pc.opportunities.map(o => (
          <Card key={o.id}>
            <VStack gap={3}>
              <HStack hAlign="between" vAlign="center">
                <Heading level={4}>{o.title}</Heading>
              </HStack>
              <HStack gap={2}>
                <Badge variant="teal" label={o.theme} />
                <Badge variant={statusVariant(o.status)} label={o.status} />
              </HStack>
              <Text type="body">{o.hypothesis}</Text>
              {o.sizing ? (
                <Text type="body">
                  <b>Sizing:</b> {o.sizing}
                </Text>
              ) : null}
              {asList(o.evidence).length ? (
                <VStack gap={1}>
                  <Text type="supporting" color="secondary">
                    Evidence
                  </Text>
                  <List density="compact">
                    {asList(o.evidence).map((e, i) => (
                      <ListItem key={i} label={e} />
                    ))}
                  </List>
                </VStack>
              ) : null}
              {asList(o.confirm).length ? (
                <VStack gap={1}>
                  <Text type="supporting" color="secondary">
                    Questions to ask the customer
                  </Text>
                  <List density="compact">
                    {asList(o.confirm).map((q, i) => (
                      <ListItem key={i} label={q} />
                    ))}
                  </List>
                </VStack>
              ) : null}
              {o.caveat ? <Banner status="warning" title="Caveat" description={o.caveat} /> : null}
            </VStack>
          </Card>
        ))}
      </Grid>
      <Heading level={3}>Recommendations</Heading>
      <VStack gap={3}>
        {pc.recommendations.map((r, i) => (
          <Card key={i}>
            <VStack gap={2}>
              <HStack gap={2} vAlign="center">
                <Badge variant="teal" label={r.theme} />
                <Heading level={4}>{r.title}</Heading>
              </HStack>
              <Text type="body">{r.text}</Text>
              <Text type="supporting" color="secondary">
                Basis: {r.basis}
              </Text>
            </VStack>
          </Card>
        ))}
      </VStack>
    </VStack>
  );
}

// ------------------------------------------------------------------ data & method tab

function DataMethodTab({data}: {data: DemoData}) {
  const issueRows = data.issues.map((i, n) => ({...i, id: String(n)}));
  const issueColumns: TableColumn<(typeof issueRows)[number]>[] = [
    {
      key: 'severity',
      header: 'Severity',
      width: pixel(100),
      renderCell: i => <Badge variant={severityVariant(i.severity)} label={i.severity} />,
    },
    {key: 'check', header: 'Check', width: proportional(1)},
    {key: 'table', header: 'Table', width: pixel(140)},
    {key: 'location', header: 'Location', width: pixel(120)},
    {key: 'explanation', header: 'Explanation', width: proportional(1.6)},
    {key: 'fix', header: 'Suggested fix', width: proportional(1.4)},
  ];
  return (
    <VStack gap={6}>
      <Heading level={3}>Data readiness and validation</Heading>
      <Text type="body">
        The pipeline reads the Excel pack, classifies every sheet into the internal model, maps
        columns and units, and only then calculates. Cross-sheet validation issues are reviewed
        below; in the full Streamlit app the KAM decides per issue (exclude rows or keep and flag)
        before any number is computed. This web demo applies the default headless decisions.
      </Text>
      <Card>
        <VStack gap={4}>
          <Heading level={4}>Validation issues ({issueRows.length})</Heading>
          <Table data={issueRows} columns={issueColumns} idKey="id" density="compact" dividers="rows" hasHover />
        </VStack>
      </Card>
      <Card>
        <VStack gap={3}>
          <Heading level={4}>Method notes</Heading>
          <List>
            <ListItem label='All numbers are deterministic pandas arithmetic from metrics.py; no LLM and no vector search is involved in any figure.' />
            <ListItem label='Each metric carries a status (CALCULATED / ALLOCATED / ESTIMATED), a formula, and a Low-High range where assumptions vary.' />
            <ListItem label='Water, energy and CO2 savings are relative to the selected baseline in the pack; baseline intensities are illustrative pack values.' />
            <ListItem label='Data is the synthetic sample pack (data/pack.xlsx): fictional customers, sites and activity for demo purposes only.' />
            <ListItem label='The Streamlit app (repo root) remains the reference implementation with upload, review workflow, Analyst chat and PowerPoint export; this Astryx app re-presents its computed results.' />
          </List>
        </VStack>
      </Card>
    </VStack>
  );
}

// ------------------------------------------------------------------ app

export default function App() {
  const [data, setData] = useState<DemoData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState('portfolio');
  const [customerId, setCustomerId] = useState<string>('');

  useEffect(() => {
    fetch('data/demo-data.json')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d: DemoData) => {
        setData(d);
        setCustomerId(d.customers[0]?.id ?? '');
      })
      .catch(e => setError(String(e)));
  }, []);

  const openCustomer = (cid: string) => {
    setCustomerId(cid);
    setTab('customer');
  };

  return (
    <Layout
      height="fill"
      content={
        <LayoutContent padding={6}>
          <VStack gap={6}>
            <HStack gap={3} vAlign="center">
              <Heading level={1}>Customer Value &amp; Sustainability Review</Heading>
              <Badge variant="purple" label="Astryx UI demo" />
            </HStack>
            <Text type="supporting" color="secondary">
              Lindström x Since AI 2026, Team Predictable. A tool for the Key Account Manager:
              portfolio view, one customer at a time, and a yearly-meeting brief with
              evidence-backed topics.
            </Text>
            <Banner
              status="warning"
              title="Synthetic sample data"
              description="All customers, sites and numbers come from the synthetic data pack (data/pack.xlsx). Figures are computed by the repo's deterministic pipeline; they demo the workflow, not real customer facts."
            />
            {error ? <Banner status="error" title="Could not load demo data" description={error} /> : null}
            {!data && !error ? <Spinner label="Loading demo data" /> : null}
            {data ? (
              <>
                <TabList value={tab} onChange={setTab} hasDivider>
                  <Tab value="portfolio" label="Portfolio" />
                  <Tab value="customer" label="Customer" />
                  <Tab value="brief" label="Meeting brief" />
                  <Tab value="method" label="Data &amp; method" />
                </TabList>
                {tab === 'portfolio' ? <PortfolioTab data={data} onOpenCustomer={openCustomer} /> : null}
                {tab === 'customer' ? <CustomerTab data={data} customerId={customerId} onChange={setCustomerId} /> : null}
                {tab === 'brief' ? <MeetingBriefTab data={data} customerId={customerId} onChange={setCustomerId} /> : null}
                {tab === 'method' ? <DataMethodTab data={data} /> : null}
              </>
            ) : null}
          </VStack>
        </LayoutContent>
      }
    />
  );
}
